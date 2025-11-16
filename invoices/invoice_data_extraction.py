from PyPDF2 import PdfReader, PdfWriter
import json
import os
import logging
import time
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import google.genai as genai  # ✅ new official SDK

# --------------------------------------------------------
# Load environment variables
# --------------------------------------------------------
load_dotenv()
print("✅ Loaded environment variables for PDF parsing.")

# pdf_path = r"C:\NIA\NIA 2W RETAIL ESTIMATE & INVOICE\NIA 2W RETAIL ESTIMATE & INVOICE\INVOICE\CSPBGQV4K - Final Repair Invoice.pdf"


# --------------------------------------------------------
# PDF Parser Class
# --------------------------------------------------------
class PDFParser:

    def __init__(self):
        self.app_id = os.getenv("PDF_APP_ID")
        self.app_key = os.getenv("PDF_APP_KEY")

        if not self.app_id or not self.app_key:
            raise ValueError("❌ Missing PDF_APP_ID or PDF_APP_KEY in .env file")

        self.headers = {"app_id": self.app_id, "app_key": self.app_key}

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )

    # --------------------------------------------------------
    # Read PDF by pages and upload to Mathpix
    # --------------------------------------------------------
    def read_pdf_by_pages(self, pdf_path: str):
        if not os.path.exists(pdf_path):
            logging.error("PDF file not found.")
            return False, 0

        if not pdf_path.lower().endswith(".pdf"):
            logging.error("File is not a PDF.")
            return False, 0

        try:
            reader = PdfReader(pdf_path)
            total_pages = len(reader.pages)
            if total_pages == 0:
                logging.error("No pages found in PDF.")
                return False, 0
        except Exception as e:
            logging.error(f"Failed to read PDF file: {e}")
            return False, 0

        responses = {}
        final_response = {}
        temp_files = []

        # --------------------------------------------------------
        # Upload each page to Mathpix
        # --------------------------------------------------------
        for idx, page in enumerate(reader.pages, start=1):
            page_file = f"temp_page_{idx}.pdf"
            temp_files.append(page_file)

            try:
                writer = PdfWriter()
                writer.add_page(page)
                with open(page_file, "wb") as f:
                    writer.write(f)

                options = {
                    "conversion_formats": {"html": True},
                    "include_diagram_text": True,
                    "include_page_info": True,
                }

                with open(page_file, "rb") as f:
                    response = requests.post(
                        "https://api.mathpix.com/v3/pdf",
                        headers=self.headers,
                        files={"file": f},
                        data={"options_json": json.dumps(options)},
                        timeout=60,
                    )

                logging.info(f"Upload response for page {idx}: {response.text}")

                if response.status_code != 200:
                    logging.error(f"Upload failed for page {idx}. Status: {response.status_code}")
                    responses[idx] = False
                    continue

                try:
                    result = response.json()
                except json.JSONDecodeError:
                    logging.error(f"Invalid JSON in upload response for page {idx}")
                    responses[idx] = False
                    continue

                pdf_id = result.get("pdf_id")
                if not pdf_id:
                    logging.error(f"PDF ID not found for page {idx}: {result}")
                    responses[idx] = False
                else:
                    logging.info(f"✅ Page {idx} uploaded successfully. PDF ID: {pdf_id}")
                    responses[idx] = pdf_id

            except Exception as e:
                logging.error(f"Error processing page {idx}: {e}")
                responses[idx] = False
            finally:
                if os.path.exists(page_file):
                    try:
                        os.remove(page_file)
                        logging.info(f"🧹 Removed temp file: {page_file}")
                    except OSError as e:
                        logging.warning(f"Failed to remove temp file {page_file}: {e}")

        # --------------------------------------------------------
        # Poll Mathpix until pages are processed
        # --------------------------------------------------------
        successful_uploads = [pid for pid in responses.values() if pid]
        if not successful_uploads:
            logging.error("No pages were uploaded successfully.")
            return False, 0

        max_retries = 10
        poll_interval = 5

        for idx, pid in responses.items():
            if not pid:
                logging.warning(f"Skipping page {idx} (upload failed)")
                continue

            retry_count = 0
            state = "unknown"

            while retry_count < max_retries:
                try:
                    logging.info(f"Checking status for page {idx} (Attempt {retry_count + 1})")
                    status_url = f"https://api.mathpix.com/v3/pdf/{pid}"
                    poll = requests.get(status_url, headers=self.headers, timeout=30)

                    if poll.status_code != 200:
                        logging.error(f"Status check failed for page {idx}. HTTP {poll.status_code}")
                        break

                    job_status = poll.json()
                    state = job_status.get("status", "unknown")
                    logging.info(f"Page {idx} status: {state}")

                    if state == "completed":
                        break
                    elif state == "error":
                        logging.error(f"Processing error for page {idx}: {job_status.get('error')}")
                        break
                    else:
                        time.sleep(poll_interval)
                        retry_count += 1

                except requests.exceptions.RequestException as e:
                    logging.error(f"Network error while checking page {idx}: {e}")
                    retry_count += 1
                    time.sleep(poll_interval)
                except Exception as e:
                    logging.error(f"Unexpected error while polling page {idx}: {e}")
                    break

            if state != "completed":
                logging.error(f"Page {idx} failed or timed out.")
                continue

            # --------------------------------------------------------
            # Fetch processed HTML
            # --------------------------------------------------------
            try:
                url = f"https://api.mathpix.com/v3/pdf/{pid}.html"
                response = requests.get(url, headers=self.headers, timeout=60)
                print(f"📄 HTML fetch response for page {idx}: {response.status_code}")

                if response.status_code == 200:
                    final_response[idx] = response.text
                    logging.info(f"✅ Page {idx} HTML fetched successfully.")
                else:
                    final_response[idx] = False
                    logging.error(f"Failed to fetch HTML for page {idx}. HTTP {response.status_code}")
            except Exception as e:
                final_response[idx] = False
                logging.error(f"Error downloading HTML for page {idx}: {e}")

        # --------------------------------------------------------
        # Save results to JSON
        # --------------------------------------------------------
        if not final_response:
            logging.error("No HTML responses to save.")
            return False, 0

        try:
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            final_json_path = f"{base_name}_output.json"
            with open(final_json_path, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in final_response.items()}, f, ensure_ascii=False, indent=2)

            logging.info(f"✅ Results saved to {final_json_path} ({len(final_response)} pages).")
        except Exception as e:
            logging.error(f"Failed to save results: {e}")
            return False, 0

        return final_json_path, total_pages


# --------------------------------------------------------
# Run the script and pass to JSON converter
# --------------------------------------------------------

# parser = PDFParser()
# result, total = parser.read_pdf_by_pages()



import os
import json
from bs4 import BeautifulSoup
import google.genai as genai

def process_invoice_json_with_gemini(result, total):
    """
    Function to process the Mathpix output JSON and extract structured invoice data using Gemini.
    Parameters:
        result (str): Path to Mathpix JSON file (output of PDFParser)
        total (int): Total pages processed (optional, just for logging)
    """
    if result:
        print(f"\n🎉 Successfully processed {total} pages.")
        print(f"📁 Output saved to: {result}")

        # --------------------------------------------------------
        # Pass first function result to second part
        # --------------------------------------------------------
        json_file = result  # ✅ dynamically use output from PDFParser
        base_name = os.path.splitext(os.path.basename(json_file))[0]
        final_json_output = f"{base_name}_full_structured.json"

        # === Gemini part starts here (same as your second code) ===
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY_Gemini"))

        def html_to_text(html):
            soup = BeautifulSoup(html, "html.parser")
            return soup.get_text(separator="\n").strip()

        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        print(f"✅ Loaded {len(data)} page(s)")

        full_text = "\n".join([html_to_text(v) for v in data.values() if v])
        print("📄 Combined invoice text extracted.")

        prompt = f"""
You are an expert in invoice understanding and data extraction.

Your task is to extract **all possible structured information** from the following invoice text and return it as a clean, valid JSON object.

Rules:
- Return **only valid JSON**, no markdown, code fences, or explanations.
- If a field is missing, return it as an empty string ("").
- Keep currency symbols (₹, $, €, etc.) intact.
- Include all available fields even if partially present.
- Maintain nested structure exactly as shown.

Required JSON structure:
{{ ... same JSON structure ... }}

Now extract and return JSON only.
Invoice text:
\"\"\"{full_text}\"\"\""""
        print("🤖 Sending to Gemini for structured invoice extraction...")


        # Duu to high cost of Gemini-2.5, using Gemini-1.5 for now
        # response = client.models.generate_content(
        #     model="gemini-2.5-flash",
        #     contents=prompt
        # )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        try:
            structured_json = json.loads(response.text)
        except json.JSONDecodeError:
            print("⚠️ Gemini returned non-JSON output, attempting cleanup...")
            cleaned = response.text.strip().split("```json")[-1].split("```")[0]
            structured_json = json.loads(cleaned)

        structured_json["raw_text"] = full_text.strip()

        with open(final_json_output, "w", encoding="utf-8") as f:
            json.dump(structured_json, f, indent=2, ensure_ascii=False)

        print(f"\n🎉 Full structured invoice saved to: {final_json_output}")
        return final_json_output

    else:
        print("\n❌ PDF processing failed.")
        return None

