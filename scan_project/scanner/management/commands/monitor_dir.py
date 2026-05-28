import concurrent.futures
import hashlib
import json
import os
import shutil
import signal
import time

import environ
import pytesseract
from django.conf import settings
from django.core.management.base import BaseCommand
from ollama import Client
from pdf2image import convert_from_path
from pypdf import PdfReader
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from scanner.models import ScannedDocument

env = environ.Env()
environ.Env.read_env(os.path.join(settings.BASE_DIR, ".env"))

INPUT_DIR = env("INPUT_DIR", default="/Users/jwalker/air/scanManager/input_dir")
ERROR_DIR = env("ERROR_DIR", default="/Users/jwalker/air/scanManager/error_dir")
OLLAMA_HOST = env("OLLAMA_HOST", default="http://10.0.0.3:30068")

ollama_client = Client(host=OLLAMA_HOST, timeout=60)


class PDFHandler(FileSystemEventHandler):
    def __init__(self, executor):
        self.executor = executor
        super().__init__()

    def on_created(self, event):
        if event.is_directory:
            return

        file_path = event.src_path
        self.handle_file(file_path)

    def handle_file(self, file_path):
        if file_path.lower().endswith(".pdf"):
            print(f"New PDF detected: {file_path}")

            # Submit to thread pool instead of unbounded thread creation
            self.executor.submit(self.process_pdf, file_path)

    def process_pdf(self, file_path):
        from django.db import connection

        try:
            # Wait for file to become stable
            last_size = -1
            stable_count = 0
            max_retries = 30
            retries = 0
            while stable_count < 3 and retries < max_retries:
                try:
                    current_size = os.path.getsize(file_path)
                    if current_size == last_size and current_size > 0:
                        stable_count += 1
                    else:
                        stable_count = 0
                        last_size = current_size
                except FileNotFoundError:
                    print(f"File {file_path} vanished before it could be processed.")
                    return
                except OSError:
                    stable_count = 0
                time.sleep(1)
                retries += 1

            if retries >= max_retries:
                print(f"Timed out waiting for {file_path} to become stable.")
                return

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

            original_filename = os.path.basename(file_path)

            # Use get_or_create to avoid race conditions with multiple concurrent handlers
            doc, created = ScannedDocument.objects.get_or_create(
                file_hash=file_hash,
                defaults={
                    "original_path": file_path,
                    "original_filename": original_filename,
                    "suggested_filename": "",
                    "summary": "Processing...",
                    "status": "processing",
                },
            )

            if not created:
                print(
                    f"File {file_path} (hash: {file_hash[:8]}...) has already "
                    f"been processed. Ignoring duplicate."
                )
                if doc.original_path != file_path:
                    try:
                        os.remove(file_path)
                        print(f"Deleted duplicate file: {file_path}")
                    except Exception as e:
                        print(f"Failed to delete duplicate file {file_path}: {e}")
                else:
                    print(
                        "Duplicate event for the exact same file "
                        f"path: {file_path}. Skipping deletion."
                    )
                return

            doc_id = doc.id

            print(f"Reading {file_path} with pypdf...")
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"

            # If text is very short or empty, the PDF might be an image/scan
            if len(text.strip()) < 50:
                print(
                    "Could not extract sufficient text with pypdf. Attempting "
                    f"OCR on {file_path}..."
                )
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
            2. Suggest a concise filename for this document in the format 
                YYYYMMDD_TitleCase. Attempt to find a date from the document text. 
                Example Filenames: 20231024_VetInvoice.pdf or 20230105_TaxReturn.pdf. 
                Ensure the filename ends with .pdf.
            
            Return the result EXACTLY as a JSON object with two keys: "summary" and 
            "filename". Do not include any other text or markdown formatting.
            """
            doc_prompt = f"""
            Document Text:
            {text}
            """

            print("Sending to Ollama...")
            response = ollama_client.chat(
                model="gemma4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": doc_prompt},
                ],
                stream=False,
            )
            response_contents = response.message.content
            print(f"Response received from Ollama: {response_contents}")

            try:
                response_contents = response_contents.strip()
                if response_contents.startswith("```json"):
                    response_contents = response_contents[7:]
                if response_contents.endswith("```"):
                    response_contents = response_contents[:-3]
                response_contents = response_contents.strip()
                result = json.loads(response_contents)
                summary = result.get("summary", "No summary generated")
                filename = result.get(
                    "filename", f"Unknown_Document_{int(time.time())}.pdf"
                )
            except json.JSONDecodeError:
                print("Failed to parse JSON from Ollama.")
                summary = response_contents
                filename = f"ScannedDoc_{int(time.time())}.pdf"

            # Update DB entry
            doc = ScannedDocument.objects.get(id=doc_id)
            doc.suggested_filename = filename
            doc.summary = summary
            doc.status = "pending"
            doc.save()
            print(f"Successfully processed {original_filename}")

        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            if "doc_id" in locals():
                try:
                    doc = ScannedDocument.objects.get(id=doc_id)
                    doc.summary = f"Error processing file: {e}"
                    doc.status = "ignored"
                    doc.save()

                    # Move the physical file to the error directory
                    os.makedirs(ERROR_DIR, exist_ok=True)
                    error_path = os.path.join(ERROR_DIR, os.path.basename(file_path))
                    if os.path.exists(file_path):
                        shutil.move(file_path, error_path)
                        print(f"Moved failed file to {error_path}")
                except Exception as save_e:
                    print(f"Failed to update document status or move file: {save_e}")
        finally:
            connection.close()


class Command(BaseCommand):
    help = "Monitors the input directory for new PDFs and processes them"

    def handle(self, *args, **options):
        # Ensure directories exist
        os.makedirs(INPUT_DIR, exist_ok=True)
        os.makedirs(ERROR_DIR, exist_ok=True)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        event_handler = PDFHandler(executor)

        # Process existing files
        self.stdout.write(
            self.style.SUCCESS(f"Checking for existing PDFs in {INPUT_DIR}...")
        )
        for filename in os.listdir(INPUT_DIR):
            file_path = os.path.join(INPUT_DIR, filename)
            if os.path.isfile(file_path):
                event_handler.handle_file(file_path)

        observer = Observer()
        observer.schedule(event_handler, INPUT_DIR, recursive=False)
        observer.start()

        # Handle SIGTERM for graceful shutdown
        def sigterm_handler(signum, frame):
            self.stdout.write(
                self.style.WARNING("\nSIGTERM received. Shutting down...")
            )
            observer.stop()

        signal.signal(signal.SIGTERM, sigterm_handler)

        self.stdout.write(
            self.style.SUCCESS(f"Started monitoring {INPUT_DIR} for new PDFs...")
        )

        try:
            while observer.is_alive():
                observer.join(1)
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING("\nKeyboardInterrupt received. Shutting down...")
            )
            observer.stop()

        observer.join()
        executor.shutdown(wait=True)
