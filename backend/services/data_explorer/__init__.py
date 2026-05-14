"""Database Data Explorer service package.

Keep this package initializer lightweight so utility modules such as
``table_ref`` and ``redaction`` can be imported without constructing the API
service and its Pydantic response models.
"""
