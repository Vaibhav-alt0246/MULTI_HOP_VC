import os
import json
from pathlib import Path
from pypdf import PdfReader

# Setup strict paths relative to the project root
ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

# Ensure directories exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

def clean_text(text):
    """Cleans up messy PDF layouts, page numbers, and trailing spaces."""
    if not text:
        return ""
    lines = text.split("\n")
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    return " ".join(cleaned_lines)

def extract_claims_from_text(text):
    """
    Heuristic function to catch key business and technical claims.
    This acts as a bridge before integrating LLMs or advanced NLP engines.
    """
    claims = []
    # Simple rule-based keywords for testing
    keywords = ["infrastructure", "architecture", "ai", "mesh", "database", "ledger", "security", "zero-trust"]
    
    sentences = text.split(". ")
    for sentence in sentences:
        if any(kw in sentence.lower() for kw in keywords):
            claims.append(sentence.strip())
            
    return claims[:5]  # Limit to top 5 assertions for testing

def process_single_pdf(pdf_path):
    print(f"\n[Processing] Found file: {pdf_path.name}")
    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        print(f" -> Total pages detected: {total_pages}")
        
        full_text = ""
        for idx, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
        
        cleaned = clean_text(full_text)
        print(f" -> Extracted character count: {len(cleaned)}")
        
        if len(cleaned) < 50:
            print(" -> [Warning] Very little text extracted. PDF might be a scanned image or unreadable text layers.")
            
        # Extract basic assertions
        extracted_assertions = extract_claims_from_text(cleaned)
        print(f" -> Found {len(extracted_assertions)} technical claims/keywords.")

        # Build structured data object
        structured_data = {
            "source_file": pdf_path.name,
            "file_status": "Success",
            "total_pages": total_pages,
            "metrics": {
                "character_count": len(cleaned),
                "word_count": len(cleaned.split())
            },
            "claims_extracted": extracted_assertions
        }
        
        # Save output JSON
        output_filename = f"{pdf_path.stem}_structured.json"
        output_path = PROCESSED_DIR / output_filename
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(structured_data, f, indent=4)
            
        print(f" -> [Success] Saved output to: {output_path}")

    except Exception as e:
        print(f" -> [Error] Failed to read {pdf_path.name}: {e}")

def run_extraction_pipeline():
    print("="*50)
    print("STARTING STARTUP CLAIMS EXTRACTOR PIPELINE")
    print(f"Looking for PDFs in: {RAW_DIR}")
    print("="*50)
    
    # Grab all PDF files in the raw folder
    pdf_files = list(RAW_DIR.glob("*.pdf"))
    
    if not pdf_files:
        print(f"[Warning] No PDF files (.pdf) found in '{RAW_DIR}'.")
        print("Please ensure your pitch decks are saved into that directory and try again.")
        return

    print(f"Found {len(pdf_files)} PDF file(s) to process.")
    for pdf_file in pdf_files:
        process_single_pdf(pdf_file)
        
    print("\n"+"="*50)
    print("PIPELINE PROCESSING COMPLETE")
    print("="*50)

if __name__ == "__main__":
    run_extraction_pipeline()