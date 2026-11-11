from rest_framework import serializers
from .models import Article

class ArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = ['id', 'title', 'slug', 'author', 'content', 'published_at']
        read_only_fields = ['id', 'published_at']
