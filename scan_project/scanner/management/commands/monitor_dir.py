import os
import time
import json
from pathlib import Path
from pypdf import PdfReader
from pdf2image import convert_from_path
import pytesseract
from django.core.management.base import BaseCommand
from django.conf import settings
from scanner.models import ScannedDocument
from ollama import Client
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import environ

env = environ.Env()
environ.Env.read_env(os.path.join(settings.BASE_DIR, '.env'))

INPUT_DIR = env('INPUT_DIR', default='/Users/jwalker/air/scanManager/input_dir')

ollama_client = Client(host="http://10.0.0.3:30068")

import threading
import hashlib

class PDFHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        file_path = event.src_path
        if file_path.lower().endswith('.pdf'):
            print(f"New PDF detected: {file_path}")

            # Wait a short moment to ensure the file is written to disk before hashing
            time.sleep(30)

            # Calculate SHA-256 hash
            sha256_hash = hashlib.sha256()
            try:
                with open(file_path, "rb") as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
                file_hash = sha256_hash.hexdigest()
            except Exception as e:
                print(f"Error hashing {file_path}: {e}")
                return

            # Check if this exact file has already been processed
            if ScannedDocument.objects.filter(file_hash=file_hash).exists():
                print(f"File {file_path} (hash: {file_hash[:8]}...) has already been processed. Ignoring duplicate.")
                return

            # Create DB entry immediately as 'processing'
            original_filename = os.path.basename(file_path)
            doc = ScannedDocument.objects.create(
                original_path=file_path,
                original_filename=original_filename,
                file_hash=file_hash,
                suggested_filename='',
                summary='Processing...',
                status='processing'
            )

            # Run the slow process in a background thread to unblock the observer
            thread = threading.Thread(target=self.process_pdf, args=(doc.id, file_path, original_filename))
            thread.daemon = True
            thread.start()

    def process_pdf(self, doc_id, file_path, original_filename):
        # Wait a moment to ensure file is fully written
        time.sleep(60)

        try:
            print(f"Reading {file_path} with pypdf...")
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            
            # If text is very short or empty, the PDF might be an image/scan
            if len(text.strip()) < 50:
                print(f"Could not extract sufficient text with pypdf. Attempting OCR on {file_path}...")
                images = convert_from_path(file_path)
                text = ""
                for img in images:
                    text += pytesseract.image_to_string(img) + "\n"

            if not text.strip():
                print(f"Could not extract text from {file_path} via pypdf or OCR.")
                text = "[No text could be extracted from this PDF]"
            else:
                print(f"Extracted text from {file_path} successfully.")

            # Truncate text if too long to save token limit on simple local models
            text = text[:4000]

            system_prompt = """
            Analyze the following document text.
            1. Provide a brief summary of what the document is about (max 3 sentences).
            2. Suggest a concise filename for this document in the format YYYYMMDD_TitleCase. Attempt to find a date from the document text. Example Filenames: 20231024_VetInvoice.pdf or 20230105_TaxReturn.pdf. Ensure the filename ends with .pdf.
            
            Return the result EXACTLY as a JSON object with two keys: "summary" and "filename". Do not include any other text or markdown formatting.
            """
            doc_prompt = f"""
            Document Text:
            {text}
            """

            print("Sending to Ollama...")
            response = ollama_client.chat(
                model="gemma4",
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": doc_prompt}],
                stream=False
            )
            response_contents = response.message.content
            print(f"Response received from Ollama: {response_contents}")
            
            try:
                response_contents = response_contents.strip().strip('```json').strip('```')
                result = json.loads(response_contents)
                summary = result.get('summary', 'No summary generated')
                filename = result.get('filename', f"Unknown_Document_{int(time.time())}.pdf")
            except json.JSONDecodeError:
                print("Failed to parse JSON from Ollama.")
                summary = response_contents
                filename = f"ScannedDoc_{int(time.time())}.pdf"

            # Update DB entry
            doc = ScannedDocument.objects.get(id=doc_id)
            doc.suggested_filename = filename
            doc.summary = summary
            doc.status = 'pending'
            doc.save()
            print(f"Successfully processed {original_filename}")

        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            doc = ScannedDocument.objects.get(id=doc_id)
            doc.summary = f"Error processing file: {e}"
            doc.status = 'ignored'
            doc.save()


class Command(BaseCommand):
    help = 'Monitors the input directory for new PDFs and processes them'

    def handle(self, *args, **options):
        # Ensure directories exist
        os.makedirs(INPUT_DIR, exist_ok=True)

        event_handler = PDFHandler()
        observer = Observer()
        observer.schedule(event_handler, INPUT_DIR, recursive=False)
        observer.start()

        self.stdout.write(
            self.style.SUCCESS(f'Started monitoring {INPUT_DIR} for new PDFs...'))

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
