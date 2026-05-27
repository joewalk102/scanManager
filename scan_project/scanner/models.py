from django.db import models

class ScannedDocument(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('ignored', 'Ignored'),
        ('renamed', 'Renamed'),
    )

    original_path = models.CharField(max_length=512)
    original_filename = models.CharField(max_length=255)
    suggested_filename = models.CharField(max_length=255)
    summary = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.original_filename
