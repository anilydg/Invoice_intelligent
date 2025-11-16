from rest_framework import serializers
from .models import Invoice, InvoiceItem

class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = ['id', 'description', 'quantity', 'price']

class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True)

    class Meta:
        model = Invoice
        fields = ['id', 'client_name', 'date', 'total', 'items']

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        invoice = Invoice.objects.create(**validated_data)
        total = 0
        for item_data in items_data:
            InvoiceItem.objects.create(invoice=invoice, **item_data)
            total += item_data['quantity'] * item_data['price']
        invoice.total = total
        invoice.save()
        return invoice
