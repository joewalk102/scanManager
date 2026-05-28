import os
import shutil

from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string

from scan_project import config

from .models import ScannedDocument

OUTPUT_DIR = config.OUTPUT_DIR


def document_list(request):
    documents = ScannedDocument.objects.filter(
        status__in=["pending", "processing"]
    ).order_by("-created_at")
    max_id = documents.aggregate(max_id=Max("id"))["max_id"] or 0
    return render(
        request,
        "scanner/document_list.html",
        {"documents": documents, "max_id": max_id},
    )


def document_row(request, doc_id):
    doc = get_object_or_404(ScannedDocument, id=doc_id)
    return render(request, "scanner/partials/document_row.html", {"doc": doc})


def poll_new_documents(request):
    try:
        last_id = int(request.GET.get("last_id", 0))
    except ValueError:
        last_id = 0

    new_docs = ScannedDocument.objects.filter(
        id__gt=last_id, status__in=["pending", "processing"]
    ).order_by("-created_at")

    if not new_docs:
        return HttpResponse("")

    new_max = new_docs.aggregate(max_id=Max("id"))["max_id"] or last_id

    html = ""
    for doc in new_docs:
        html += render_to_string(
            "scanner/partials/document_row.html", {"doc": doc}, request=request
        )

    oob_input = f'<input type="hidden" id="last_id" name="last_id" value="{new_max}" hx-swap-oob="true">'
    return HttpResponse(html + oob_input)


def error_row(doc_id, msg):
    return HttpResponse(
        f'<tr id="doc-row-{doc_id}"><td colspan="4" class="text-danger fw-bold align-middle">'
        f"Error: {msg} "
        f'<button class="btn btn-sm btn-outline-secondary ms-2" onclick="location.reload()">Reload</button>'
        f"</td></tr>"
    )


def ignore_document(request, doc_id):
    if request.method == "POST":
        doc = get_object_or_404(ScannedDocument, id=doc_id)
        doc.status = "ignored"
        doc.save()

        # Delete the physical file to prevent buildup
        try:
            if os.path.exists(doc.original_path):
                os.remove(doc.original_path)
        except OSError as e:
            print(f"Error deleting ignored file {doc.original_path}: {e}")

        return HttpResponse("")  # Return empty response to remove the row via HTMX
    return HttpResponse("Invalid request", status=400)


def rename_document(request, doc_id):
    if request.method == "POST":
        doc = get_object_or_404(ScannedDocument, id=doc_id)
        new_filename = request.POST.get("new_filename")

        if not new_filename:
            return error_row(doc_id, "Filename is required.")

        # Sanitize input to prevent path traversal
        new_filename = os.path.basename(new_filename)

        if not new_filename:
            return error_row(doc_id, "Invalid filename provided.")

        if not new_filename.lower().endswith(".pdf"):
            new_filename += ".pdf"

        original_path = doc.original_path
        if not os.path.exists(original_path):
            return error_row(doc_id, "Original file not found on disk.")

        new_path = os.path.join(OUTPUT_DIR, new_filename)

        if os.path.exists(new_path):
            return error_row(doc_id, "A document with that filename already exists.")

        # Ensure output dir exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Move the file
        try:
            shutil.move(original_path, new_path)
            doc.status = "renamed"
            doc.suggested_filename = new_filename
            doc.save()
            return HttpResponse("")  # Return empty response to remove the row via HTMX
        except (OSError, IOError) as e:
            return error_row(doc_id, f"Failed to move file: {e}")

    return HttpResponse("Invalid request", status=400)
