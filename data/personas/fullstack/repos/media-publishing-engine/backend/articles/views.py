from rest_framework import viewsets, permissions
from .models import Article
from .serializers import ArticleSerializer

class ArticleViewSet(viewsets.ReadOnlyModelViewSet):
    """Expose published articles as read‑only endpoints."""
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        # Only return articles that are marked as published (future extension)
        return super().get_queryset()
