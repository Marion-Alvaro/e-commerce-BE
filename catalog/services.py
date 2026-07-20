from django.db.models import Q


def search_products(queryset, term):
    """icontains search across name/description.

    Fine for a small catalog. Once the catalog grows, this is the spot to
    swap in a MySQL FULLTEXT index — icontains forces a full table scan and
    can't use a normal B-tree index.
    """
    if not term:
        return queryset

    return queryset.filter(Q(name__icontains=term) | Q(description__icontains=term))
