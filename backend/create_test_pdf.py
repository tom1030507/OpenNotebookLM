"""Create a real PDF file for testing."""
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pathlib import Path

def create_sample_pdf():
    """Create a real PDF file for testing."""
    filename = "real_test.pdf"
    c = canvas.Canvas(filename, pagesize=letter)
    
    # Add some content
    c.drawString(100, 750, "Test PDF Document")
    c.drawString(100, 700, "This is a real PDF file created for testing purposes.")
    c.drawString(100, 650, "It contains some sample text to verify that PDF processing works.")
    c.drawString(100, 600, "Page 1 of 2")
    
    # Add a second page
    c.showPage()
    c.drawString(100, 750, "Second Page")
    c.drawString(100, 700, "This is the second page of the test document.")
    c.drawString(100, 650, "More content can be added here.")
    c.drawString(100, 600, "Page 2 of 2")
    
    c.save()
    return Path(filename)

if __name__ == "__main__":
    try:
        pdf_path = create_sample_pdf()
        print(f"Created PDF file: {pdf_path}")
        print(f"File size: {pdf_path.stat().st_size} bytes")
    except ImportError:
        print("reportlab is not installed. Installing...")
        import subprocess
        subprocess.run(["python", "-m", "pip", "install", "reportlab"])
        print("Please run this script again.")
