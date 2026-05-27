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

class PDFHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        file_path = event.src_path
        if file_path.lower().endswith('.pdf'):
            print(f"New PDF detected: {file_path}")
            self.process_pdf(file_path)

    def process_pdf(self, file_path):
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

            # Create DB entry
            original_filename = os.path.basename(file_path)
            ScannedDocument.objects.create(
                original_path=file_path,
                original_filename=original_filename,
                suggested_filename=filename,
                summary=summary,
                status='pending'
            )
            print(f"Successfully processed {original_filename}")

        except Exception as e:
            print(f"Error processing {file_path}: {e}")


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
