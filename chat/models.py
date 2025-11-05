from django.conf import settings
from django.db import models

class ChatSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_sessions'
    )
    title = models.CharField(max_length=255, default='Новый чат')
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.user.email})"


class Message(models.Model):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    role = models.CharField(
        max_length=10,
        choices=(('user', 'User'), ('ai', 'DasmGPT'))
    )
    content = models.TextField()
    data_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class ChartFile(models.Model):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='charts'
    )
    file = models.FileField(upload_to='charts/%Y/%m/%d/')
    format = models.CharField(max_length=10)  # например: png, pdf
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.format.upper()} файл для {self.session.title}"
