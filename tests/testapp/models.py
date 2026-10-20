from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)
    born = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self) -> str:
        return self.name


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    published = models.DateField(null=True, blank=True)
    in_print = models.BooleanField(default=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="books")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title


class Customer(models.Model):
    name = models.CharField(max_length=100)
    nid_number = models.CharField(max_length=17)
    phone = models.CharField(max_length=20)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)  # not tracked: outside the fields=[...] whitelist

    def __str__(self) -> str:
        return self.name


class Untracked(models.Model):
    value = models.CharField(max_length=20)

    def __str__(self) -> str:
        return self.value
