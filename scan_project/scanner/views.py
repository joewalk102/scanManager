import os
import shutil
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.conf import settings
from .models import ScannedDocument
import environ

env = environ.Env()
environ.Env.read_env(os.path.join(settings.BASE_DIR, '.env'))
OUTPUT_DIR = env('OUTPUT_DIR', default='/Users/jwalker/air/scanManager/output_dir')

def document_list(request):
    documents = ScannedDocument.objects.filter(status='pending').order_by('-created_at')
    return render(request, 'scanner/document_list.html', {'documents': documents})

def ignore_document(request, doc_id):
    if request.method == "POST":
        doc = get_object_or_404(ScannedDocument, id=doc_id)
        doc.status = 'ignored'
        doc.save()
        return HttpResponse("") # Return empty response to remove the row via HTMX
    return HttpResponse("Invalid request", status=400)

def rename_document(request, doc_id):
    if request.method == "POST":
        doc = get_object_or_404(ScannedDocument, id=doc_id)
        new_filename = request.POST.get('new_filename')
        
        if not new_filename:
            return HttpResponse("Filename is required", status=400)
            
        if not new_filename.lower().endswith('.pdf'):
            new_filename += '.pdf'
            
        original_path = doc.original_path
        if not os.path.exists(original_path):
            return HttpResponse("Original file not found", status=404)
            
        new_path = os.path.join(OUTPUT_DIR, new_filename)
        
        # Ensure output dir exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Move the file
        try:
            shutil.move(original_path, new_path)
            doc.status = 'renamed'
            doc.suggested_filename = new_filename
            doc.save()
            return HttpResponse("") # Return empty response to remove the row via HTMX
        except Exception as e:
            return HttpResponse(f"Error moving file: {e}", status=500)
            
    return HttpResponse("Invalid request", status=400)
