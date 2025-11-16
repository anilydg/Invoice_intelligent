from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Invoice
from .invoice_data_extraction import process_invoice_json_with_gemini
import tempfile
import os
import time
import json
from .invoice_data_extraction import PDFParser, process_invoice_json_with_gemini

@api_view(['GET'])
def get_invoices(request):
    invoices = list(Invoice.objects.values())
    return Response(invoices)

@api_view(['POST'])
def create_invoice(request):
    client_name = request.data.get('client_name')
    description = request.data.get('description')
    amount = request.data.get('amount')

    if not all([client_name, description, amount]):
        return Response({"error": "All fields required"}, status=status.HTTP_400_BAD_REQUEST)

    invoice = Invoice.objects.create(
        client_name=client_name,
        description=description,
        amount=amount
    )
    return Response({
        "id": invoice.id,
        "client_name": invoice.client_name,
        "description": invoice.description,
        "amount": str(invoice.amount),
        "date": invoice.date
    }, status=status.HTTP_201_CREATED)

@api_view(['DELETE'])
def delete_invoice(request, pk):
    try:
        invoice = Invoice.objects.get(pk=pk)
    except Invoice.DoesNotExist:
        return Response({"error": "Invoice not found"}, status=status.HTTP_404_NOT_FOUND)

    invoice.delete()
    return Response({"message": "Invoice deleted successfully"})




@api_view(['POST'])
def upload_invoice_pdf(request):
    """
    Accept a PDF file upload (form-data, key 'file'), pass it to PDFParser,
    then run process_invoice_json_with_gemini and return the structured JSON.
    """
    uploaded = request.FILES.get('file') or request.FILES.get('pdf')
    if not uploaded:
        return Response({"error": "PDF file is required (form-data key: 'file' or 'pdf')"},
                        status=status.HTTP_400_BAD_REQUEST)

    if not uploaded.name.lower().endswith('.pdf'):
        return Response({"error": "Uploaded file must be a PDF"},
                        status=status.HTTP_400_BAD_REQUEST)


    # save uploaded file to a temporary path
    temp_dir = tempfile.gettempdir()
    timestamp = int(time.time() * 1000)
    temp_path = os.path.join(temp_dir, f"uploaded_invoice_{timestamp}.pdf")

    try:
        with open(temp_path, 'wb') as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        # lazy import to avoid changing top-of-file imports

        try:
            parser = PDFParser()
        except Exception as e:
            return Response({"error": f"PDF parser initialization failed: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        result_json_path, total_pages = parser.read_pdf_by_pages(temp_path)
        if not result_json_path:
            return Response({"error": "PDF processing failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        structured_path = process_invoice_json_with_gemini(result_json_path, total_pages)
        if not structured_path:
            return Response({"error": "Invoice extraction failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # return the structured JSON produced by Gemini
        try:
            with open(structured_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            return Response({"error": f"Failed to read structured output: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(data, status=status.HTTP_200_OK)

    except Exception as exc:
        return Response({"error": f"Unexpected error: {str(exc)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass