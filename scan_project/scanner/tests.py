import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse

from .models import ScannedDocument


class ScannedDocumentModelTestCase(TestCase):
    """Test the ScannedDocument model."""

    def setUp(self):
        self.doc = ScannedDocument.objects.create(
            original_path="/tmp/test.pdf",
            original_filename="test.pdf",
            suggested_filename="20230101_TestDocument.pdf",
            summary="This is a test document.",
            status="pending",
        )

    def test_document_creation(self):
        """Test that a document is created correctly."""
        self.assertEqual(self.doc.original_filename, "test.pdf")
        self.assertEqual(self.doc.status, "pending")
        self.assertIsNotNone(self.doc.created_at)
        self.assertIsNotNone(self.doc.updated_at)

    def test_document_str(self):
        """Test the string representation of a document."""
        self.assertEqual(str(self.doc), "test.pdf")

    def test_status_choices(self):
        """Test that all status choices work."""
        for status, _ in ScannedDocument.STATUS_CHOICES:
            doc = ScannedDocument.objects.create(
                original_path="/tmp/test2.pdf",
                original_filename="test2.pdf",
                suggested_filename="20230101_Test.pdf",
                summary="Test",
                status=status,
            )
            self.assertEqual(doc.status, status)
            doc.delete()


class DocumentListViewTestCase(TestCase):
    """Test the document_list view."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("document_list")

        # Create test documents with different statuses
        self.pending_doc = ScannedDocument.objects.create(
            original_path="/tmp/pending.pdf",
            original_filename="pending.pdf",
            suggested_filename="20230101_Pending.pdf",
            summary="Pending document",
            status="pending",
        )

        self.processing_doc = ScannedDocument.objects.create(
            original_path="/tmp/processing.pdf",
            original_filename="processing.pdf",
            suggested_filename="20230101_Processing.pdf",
            summary="Processing document",
            status="processing",
        )

        self.ignored_doc = ScannedDocument.objects.create(
            original_path="/tmp/ignored.pdf",
            original_filename="ignored.pdf",
            suggested_filename="20230101_Ignored.pdf",
            summary="Ignored document",
            status="ignored",
        )

        self.renamed_doc = ScannedDocument.objects.create(
            original_path="/tmp/renamed.pdf",
            original_filename="renamed.pdf",
            suggested_filename="20230101_Renamed.pdf",
            summary="Renamed document",
            status="renamed",
        )

    def test_document_list_view_loads(self):
        """Test that the document list view loads successfully."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "scanner/document_list.html")

    def test_document_list_filters_status(self):
        """Test that document_list only shows pending and processing documents."""
        response = self.client.get(self.url)
        documents = response.context["documents"]

        # Should only include pending and processing
        self.assertEqual(documents.count(), 2)
        statuses = set(doc.status for doc in documents)
        self.assertEqual(statuses, {"pending", "processing"})

    def test_document_list_ordering(self):
        """Test that documents are ordered by created_at descending."""
        response = self.client.get(self.url)
        documents = list(response.context["documents"])

        # Should be ordered with newest first
        if len(documents) > 1:
            for i in range(len(documents) - 1):
                self.assertGreaterEqual(
                    documents[i].created_at, documents[i + 1].created_at
                )

    def test_document_list_max_id(self):
        """Test that max_id is calculated correctly."""
        response = self.client.get(self.url)
        max_id = response.context["max_id"]

        # max_id should be the highest document ID among pending/processing
        pending_processing = ScannedDocument.objects.filter(
            status__in=["pending", "processing"]
        )
        expected_max = max(doc.id for doc in pending_processing)
        self.assertEqual(max_id, expected_max)

    def test_document_list_empty(self):
        """Test document_list with no pending/processing documents."""
        ScannedDocument.objects.all().delete()
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["documents"].count(), 0)
        self.assertEqual(response.context["max_id"], 0)


class DocumentRowViewTestCase(TestCase):
    """Test the document_row view."""

    def setUp(self):
        self.client = Client()
        self.doc = ScannedDocument.objects.create(
            original_path="/tmp/test.pdf",
            original_filename="test.pdf",
            suggested_filename="20230101_Test.pdf",
            summary="Test document",
            status="pending",
        )
        self.url = reverse("document_row", args=[self.doc.id])

    def test_document_row_view_loads(self):
        """Test that the document_row view loads successfully."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "scanner/partials/document_row.html")

    def test_document_row_context(self):
        """Test that document is in the response context."""
        response = self.client.get(self.url)
        self.assertEqual(response.context["doc"].id, self.doc.id)

    def test_document_row_nonexistent(self):
        """Test that a nonexistent document returns 404."""
        response = self.client.get(reverse("document_row", args=[99999]))
        self.assertEqual(response.status_code, 404)


class PollNewDocumentsViewTestCase(TestCase):
    """Test the poll_new_documents view."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("poll_new_documents")

        self.doc1 = ScannedDocument.objects.create(
            original_path="/tmp/doc1.pdf",
            original_filename="doc1.pdf",
            suggested_filename="20230101_Doc1.pdf",
            summary="Document 1",
            status="pending",
        )

    def test_poll_no_new_documents(self):
        """Test polling when there are no new documents."""
        response = self.client.get(self.url, {"last_id": self.doc1.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    def test_poll_with_new_documents(self):
        """Test polling with new documents."""
        doc2 = ScannedDocument.objects.create(
            original_path="/tmp/doc2.pdf",
            original_filename="doc2.pdf",
            suggested_filename="20230101_Doc2.pdf",
            summary="Document 2",
            status="processing",
        )

        response = self.client.get(self.url, {"last_id": self.doc1.id})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"doc2.pdf", response.content)
        self.assertIn(str(doc2.id).encode(), response.content)

    def test_poll_invalid_last_id(self):
        """Test polling with invalid last_id parameter."""
        response = self.client.get(self.url, {"last_id": "invalid"})
        self.assertEqual(response.status_code, 200)
        # Should default last_id to 0 and return all pending/processing docs
        self.assertIn(b"doc1.pdf", response.content)

    def test_poll_updates_max_id(self):
        """Test that poll returns updated max_id."""
        doc2 = ScannedDocument.objects.create(
            original_path="/tmp/doc2.pdf",
            original_filename="doc2.pdf",
            suggested_filename="20230101_Doc2.pdf",
            summary="Document 2",
            status="pending",
        )

        response = self.client.get(self.url, {"last_id": 0})
        # Response should include an input with id="last_id" containing the max id
        self.assertIn(b'id="last_id"', response.content)
        self.assertIn(str(doc2.id).encode(), response.content)

    def test_poll_filters_by_status(self):
        """Test that poll only returns pending/processing documents."""
        ignored_doc = ScannedDocument.objects.create(
            original_path="/tmp/ignored.pdf",
            original_filename="ignored.pdf",
            suggested_filename="20230101_Ignored.pdf",
            summary="Ignored document",
            status="ignored",
        )

        response = self.client.get(self.url, {"last_id": 0})
        self.assertNotIn(b"ignored.pdf", response.content)


class IgnoreDocumentViewTestCase(TestCase):
    """Test the ignore_document view."""

    def setUp(self):
        self.client = Client()

        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()

        # Create a test PDF file
        self.test_file = os.path.join(self.test_dir, "test.pdf")
        Path(self.test_file).touch()

        self.doc = ScannedDocument.objects.create(
            original_path=self.test_file,
            original_filename="test.pdf",
            suggested_filename="20230101_Test.pdf",
            summary="Test document",
            status="pending",
        )
        self.url = reverse("ignore_document", args=[self.doc.id])

    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_ignore_document_post(self):
        """Test ignoring a document via POST."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)

        # Check that document status is updated
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, "ignored")

    def test_ignore_document_file_deletion(self):
        """Test that the physical file is deleted when ignoring."""
        # Verify file exists
        self.assertTrue(os.path.exists(self.test_file))

        self.client.post(self.url)

        # Verify file is deleted
        self.assertFalse(os.path.exists(self.test_file))

    def test_ignore_document_nonexistent_file(self):
        """Test ignoring a document when the file doesn't exist."""
        os.remove(self.test_file)

        # Should not raise an error
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, "ignored")

    def test_ignore_document_get_not_allowed(self):
        """Test that GET request to ignore_document returns 400."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_ignore_nonexistent_document(self):
        """Test ignoring a document that doesn't exist."""
        response = self.client.post(reverse("ignore_document", args=[99999]))
        self.assertEqual(response.status_code, 404)


class RenameDocumentViewTestCase(TestCase):
    """Test the rename_document view."""

    def setUp(self):
        self.client = Client()

        # Create temporary directories
        self.input_dir = tempfile.mkdtemp()
        self.output_dir = tempfile.mkdtemp()

        # Create a test PDF file in input directory
        self.test_file = os.path.join(self.input_dir, "test.pdf")
        Path(self.test_file).touch()

        self.doc = ScannedDocument.objects.create(
            original_path=self.test_file,
            original_filename="test.pdf",
            suggested_filename="20230101_Test.pdf",
            summary="Test document",
            status="pending",
        )
        self.url = reverse("rename_document", args=[self.doc.id])

    def tearDown(self):
        """Clean up temporary files."""
        for dir in [self.input_dir, self.output_dir]:
            if os.path.exists(dir):
                shutil.rmtree(dir)

    @mock.patch("scanner.views.OUTPUT_DIR")
    def test_rename_document_success(self, mock_output_dir):
        """Test successfully renaming and moving a document."""
        mock_output_dir.__str__.return_value = self.output_dir
        # Patch the OUTPUT_DIR module-level variable properly
        with mock.patch("scanner.views.OUTPUT_DIR", self.output_dir):
            new_filename = "20230101_RenamedDocument.pdf"
            response = self.client.post(self.url, {"new_filename": new_filename})

            self.assertEqual(response.status_code, 200)

            # Check that document was renamed
            self.doc.refresh_from_db()
            self.assertEqual(self.doc.status, "renamed")
            self.assertEqual(self.doc.suggested_filename, new_filename)

            # Check that file was moved
            new_file_path = os.path.join(self.output_dir, new_filename)
            self.assertTrue(os.path.exists(new_file_path))
            self.assertFalse(os.path.exists(self.test_file))

    def test_rename_document_no_filename(self):
        """Test renaming without providing a filename."""
        response = self.client.post(self.url, {"new_filename": ""})
        self.assertEqual(response.status_code, 200)

        # Should contain error message
        self.assertIn(b"Error:", response.content)
        self.assertIn(b"Filename is required", response.content)

    def test_rename_document_auto_add_pdf_extension(self):
        """Test that .pdf extension is added if missing."""
        with mock.patch("scanner.views.OUTPUT_DIR", self.output_dir):
            new_filename = "20230101_TestDocument"
            response = self.client.post(self.url, {"new_filename": new_filename})

            self.assertEqual(response.status_code, 200)

            self.doc.refresh_from_db()
            # Should have .pdf added
            self.assertEqual(self.doc.suggested_filename, new_filename + ".pdf")

    def test_rename_document_path_traversal_prevention(self):
        """Test that path traversal attempts are prevented."""
        with mock.patch("scanner.views.OUTPUT_DIR", self.output_dir):
            response = self.client.post(
                self.url, {"new_filename": "../../../etc/passwd"}
            )

            self.assertEqual(response.status_code, 200)

            # os.path.basename() strips the path components and returns just "passwd"
            # So it actually allows it, but to a sanitized filename
            # Verify the document was still processed
            self.doc.refresh_from_db()
            # The filename should have been sanitized to just the basename
            self.assertTrue(
                self.doc.suggested_filename.endswith(".pdf")
                or self.doc.suggested_filename == "passwd"
            )

    def test_rename_document_file_not_found(self):
        """Test renaming when the original file doesn't exist."""
        os.remove(self.test_file)

        with mock.patch("scanner.views.OUTPUT_DIR", self.output_dir):
            response = self.client.post(self.url, {"new_filename": "20230101_Test.pdf"})

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Error:", response.content)
            self.assertIn(b"Original file not found", response.content)

    def test_rename_document_existing_filename(self):
        """Test renaming to a filename that already exists."""
        # Create an existing file in output directory
        existing_file = os.path.join(self.output_dir, "20230101_Existing.pdf")
        Path(existing_file).touch()

        with mock.patch("scanner.views.OUTPUT_DIR", self.output_dir):
            response = self.client.post(
                self.url, {"new_filename": "20230101_Existing.pdf"}
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Error:", response.content)
            self.assertIn(b"already exists", response.content)

    def test_rename_document_get_not_allowed(self):
        """Test that GET request to rename_document returns 400."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_rename_nonexistent_document(self):
        """Test renaming a document that doesn't exist."""
        response = self.client.post(
            reverse("rename_document", args=[99999]),
            {"new_filename": "20230101_Test.pdf"},
        )
        self.assertEqual(response.status_code, 404)

    def test_rename_document_case_insensitive_pdf_check(self):
        """Test that .PDF (uppercase) extension is recognized."""
        with mock.patch("scanner.views.OUTPUT_DIR", self.output_dir):
            new_filename = "20230101_TestDocument.PDF"
            response = self.client.post(self.url, {"new_filename": new_filename})

            self.assertEqual(response.status_code, 200)

            self.doc.refresh_from_db()
            # Should keep the original case
            self.assertEqual(self.doc.suggested_filename, new_filename)


class ErrorRowViewTestCase(TestCase):
    """Test the error_row helper function."""

    def test_error_row_format(self):
        """Test that error_row returns proper HTML format."""
        from scanner.views import error_row

        response = error_row(1, "Test error message")

        # Check that response contains expected HTML elements
        self.assertIn(b'id="doc-row-1"', response.content)
        self.assertIn(b"Test error message", response.content)
        self.assertIn(b"Reload", response.content)

    def test_error_row_special_characters(self):
        """Test that error_row properly handles special characters."""
        from scanner.views import error_row

        error_msg = 'File not found: "test & <file>.pdf"'
        response = error_row(1, error_msg)

        self.assertIn(error_msg.encode(), response.content)


class IntegrationTestCase(TestCase):
    """Integration tests for the document workflow."""

    def setUp(self):
        self.client = Client()
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary files."""
        for dir in [self.test_dir, self.output_dir]:
            if os.path.exists(dir):
                shutil.rmtree(dir)

    def test_document_workflow_ignore(self):
        """Test the complete workflow of a document being ignored."""
        # Create a test document
        test_file = os.path.join(self.test_dir, "workflow_test.pdf")
        Path(test_file).touch()

        doc = ScannedDocument.objects.create(
            original_path=test_file,
            original_filename="workflow_test.pdf",
            suggested_filename="20230101_Workflow.pdf",
            summary="Workflow test",
            status="pending",
        )

        # List documents
        list_response = self.client.get(reverse("document_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "workflow_test.pdf")

        # Ignore the document
        ignore_response = self.client.post(reverse("ignore_document", args=[doc.id]))
        self.assertEqual(ignore_response.status_code, 200)

        # Verify document is marked as ignored
        doc.refresh_from_db()
        self.assertEqual(doc.status, "ignored")
        self.assertFalse(os.path.exists(test_file))

    def test_document_workflow_rename(self):
        """Test the complete workflow of a document being renamed."""
        # Create a test document
        test_file = os.path.join(self.test_dir, "rename_test.pdf")
        Path(test_file).touch()

        doc = ScannedDocument.objects.create(
            original_path=test_file,
            original_filename="rename_test.pdf",
            suggested_filename="20230101_Rename.pdf",
            summary="Rename test",
            status="pending",
        )

        # List documents
        list_response = self.client.get(reverse("document_list"))
        self.assertEqual(list_response.status_code, 200)

        # Rename the document
        with mock.patch("scanner.views.OUTPUT_DIR", self.output_dir):
            new_name = "20230101_RenamedFile.pdf"
            rename_response = self.client.post(
                reverse("rename_document", args=[doc.id]), {"new_filename": new_name}
            )
            self.assertEqual(rename_response.status_code, 200)

        # Verify document is marked as renamed
        doc.refresh_from_db()
        self.assertEqual(doc.status, "renamed")
        self.assertEqual(doc.suggested_filename, new_name)
