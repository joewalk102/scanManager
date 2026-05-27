# Scan Manager

A Django-based application that monitors a directory for new PDF files, extracts their text, and uses a local Ollama LLM to generate a summary and a suggested filename. Users can then review these suggestions on a web interface and either accept (rename and move) or ignore them.

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) running locally with the `llama3` model installed.
- (Optional) Docker and Docker Compose if you wish to run PostgreSQL and Ollama via containers.

## Setup

1. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install django psycopg2-binary watchdog pypdf requests python-dotenv django-environ
   ```

3. **Configure the environment:**
   Review the `.env` file located at `scan_project/.env`. 
   By default, it uses SQLite, but you can uncomment and set the `DATABASE_URL` to point to a PostgreSQL instance.
   Ensure `OLLAMA_URL`, `INPUT_DIR`, and `OUTPUT_DIR` paths match your environment.

4. **Apply database migrations:**
   ```bash
   cd scan_project
   python manage.py migrate
   ```

## Running the Application

You will need to run two separate processes to use the application fully. It is recommended to run these in separate terminal windows.

**Terminal 1: Start the Django Web Server**
```bash
source venv/bin/activate
cd scan_project
python manage.py runserver 8000
```
*The web interface will be available at http://localhost:8000.*

**Terminal 2: Start the Directory Monitor**
```bash
source venv/bin/activate
cd scan_project
python manage.py monitor_dir
```
*This process watches the `input_dir` for new PDFs and processes them using Ollama.*

## Usage

1. Start both the Django server and the monitor script.
2. Drop a PDF file into the `input_dir/` directory.
3. The monitor script will detect the file, extract the text, and query your local Ollama instance for a summary and filename.
4. Once processed, visit `http://localhost:8000`. You will see the document listed with its summary and suggested filename.
5. You can edit the suggested filename in the text box.
6. Click **Rename** to move the file to the `output_dir/` with the new name, or click **Ignore** to dismiss the suggestion. The list will update automatically without reloading the page.
