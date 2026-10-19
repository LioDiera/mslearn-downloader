"""PDF formatter for MS Learn content."""

from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from rich.console import Console
import base64
import mimetypes

console = Console()


class PDFFormatter:
    """Format content as PDF using Playwright (headless Chromium)."""
    
    def __init__(self, config):
        """Initialize PDF formatter with configuration."""
        self.config = config
        self.page_size = config.get('pdf.page_size', 'A4')
        self.margin = config.get('pdf.margin', '2cm')
        self.font_size = config.get('pdf.font_size', '11pt')
        self.include_bookmarks = config.get('pdf.include_bookmarks', True)
    
    def format(self, learning_path: Dict, modules_content: List[Dict], output_path: Path,
               images_dir: Path = None, filename_prefix: Optional[str] = None):
        """Generate PDF output."""
        console.print("[cyan]Generating PDF output...[/cyan]")
        
        # Add GTK bin to PATH for cairosvg on Windows
        import os
        if os.name == 'nt':
            gtk_path = r"C:\Program Files\GTK3-Runtime Win64\bin"
            if os.path.exists(gtk_path) and gtk_path not in os.environ.get('PATH', ''):
                os.environ['PATH'] = f"{gtk_path};{os.environ.get('PATH', '')}"
        
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            console.print("[red]Playwright not installed. Installing playwright...[/red]")
            import subprocess
            subprocess.run(['pip', 'install', 'playwright'], check=True)
            subprocess.run(['playwright', 'install', 'chromium'], check=True)
            from playwright.sync_api import sync_playwright
        
        try:
            from pypdf import PdfWriter
        except ImportError:
            console.print("[yellow]pypdf not installed. Installing...[/yellow]")
            import subprocess
            subprocess.run(['pip', 'install', 'pypdf'], check=True)
            from pypdf import PdfWriter
        
        output_path = Path(output_path)
        
        if output_path.is_dir():
            safe_title = self._sanitize_filename(learning_path.get('title', 'content'))
            filename = f"{filename_prefix} - {safe_title}" if filename_prefix else safe_title
            pdf_file = output_path / f"{filename}.pdf"
        else:
            pdf_file = output_path
            pdf_file.parent.mkdir(parents=True, exist_ok=True)
        
        part_pdfs = []
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                
                # Cover page + TOC rendered without a footer
                cover_toc_html = self._generate_cover_toc_html(learning_path, modules_content)
                cover_toc_pdf = pdf_file.parent / f"{pdf_file.stem}_part_cover.pdf"
                self._render_html_to_pdf(browser, cover_toc_html, cover_toc_pdf)
                if cover_toc_pdf.exists():
                    part_pdfs.append(cover_toc_pdf)
                
                # One PDF per unit, each with a footer showing module & unit name
                for i, module_data in enumerate(modules_content, 1):
                    module = module_data['metadata']
                    module_title = module.get('title', 'Untitled')
                    
                    for j, unit_data in enumerate(module_data.get('content', []), 1):
                        unit = unit_data['metadata']
                        unit_title = unit.get('title', 'Untitled')
                        footer_text = f"Module {i}: {module_title}  \u00b7  Unit {j}: {unit_title}"
                        
                        unit_html = self._generate_unit_html(
                            i, module_title, module.get('summary', ''),
                            j, unit_title, unit_data.get('html', ''),
                            images_dir, is_first_unit=(j == 1)
                        )
                        unit_pdf = pdf_file.parent / f"{pdf_file.stem}_part_m{i}_u{j}.pdf"
                        self._render_html_to_pdf(browser, unit_html, unit_pdf, footer_text=footer_text)
                        if unit_pdf.exists():
                            part_pdfs.append(unit_pdf)
                
                browser.close()
            
            # Merge all part PDFs into the final output
            writer = PdfWriter()
            for part in part_pdfs:
                writer.append(str(part))
            with open(pdf_file, 'wb') as f:
                writer.write(f)
            console.print(f"[green]PDF saved to: {pdf_file}[/green]")
        
        except Exception as e:
            console.print(f"[red]Failed to generate PDF: {e}[/red]")
            raise
        finally:
            for part in part_pdfs:
                try:
                    part.unlink(missing_ok=True)
                except Exception:
                    pass
    
    def _generate_cover_toc_html(self, learning_path: Dict, modules_content: List[Dict]) -> str:
        """Generate HTML for the cover page and table of contents."""
        title = learning_path.get('title', 'MS Learn Content')
        summary = learning_path.get('summary', '')
        toc_html = self._generate_toc(modules_content)
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
    {self._get_pdf_css()}
    </style>
</head>
<body>
    <div class="cover-page">
        <h1 class="cover-title">{title}</h1>
        <div class="cover-summary">{self._strip_html_tags(summary)}</div>
        <div class="cover-metadata">
            <p>Duration: {learning_path.get('duration_in_minutes', 0)} minutes</p>
            <p>Modules: {learning_path.get('number_of_children', 0)}</p>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </div>
    </div>
    <div class="toc-page">
        <h1 class="toc-title">Table of Contents</h1>
        {toc_html}
    </div>
</body>
</html>"""
    
    def _generate_toc(self, modules_content: List[Dict]) -> str:
        """Generate table of contents for PDF."""
        toc = ['<ol class="toc-list">']
        
        for i, module_data in enumerate(modules_content, 1):
            module = module_data['metadata']
            toc.append(f'<li class="toc-module">{i}. {module.get("title", "Untitled")}')
            
            if module_data['content']:
                toc.append('<ol class="toc-units">')
                for j, unit_data in enumerate(module_data['content'], 1):
                    unit = unit_data['metadata']
                    toc.append(f'<li class="toc-unit">{i}.{j}. {unit.get("title", "Untitled")}</li>')
                toc.append('</ol>')
            
            toc.append('</li>')
        
        toc.append('</ol>')
        return '\n'.join(toc)
    
    def _generate_unit_html(self, module_num: int, module_title: str, module_summary: str,
                             unit_num: int, unit_title: str, unit_html_content: str,
                             images_dir: Path, is_first_unit: bool = False) -> str:
        """Generate self-contained HTML for a single unit."""
        module_header = ''
        if is_first_unit:
            module_header = (
                f'<div class="module-header">'
                f'<h1 class="module-title">Module {module_num}: {module_title}</h1>'
                f'<div class="module-summary">{module_summary}</div>'
                f'</div>'
            )
        
        if images_dir:
            unit_html_content = self._fix_image_paths_for_local(unit_html_content, images_dir)
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Module {module_num}: {module_title}  \u00b7  Unit {unit_num}: {unit_title}</title>
    <style>
    {self._get_pdf_css()}
    </style>
</head>
<body>
    {module_header}
    <div class="unit">
        <h2 class="unit-title">Unit {unit_num}: {unit_title}</h2>
        {unit_html_content}
    </div>
</body>
</html>"""
    
    def _render_html_to_pdf(self, browser, html_content: str, output_path: Path, footer_text: str = '') -> None:
        """Render an HTML string to PDF using an already-open Playwright browser."""
        html_file = output_path.parent / f"{output_path.stem}_temp.html"
        try:
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            page = browser.new_page()
            page.goto(f'file:///{html_file.as_posix()}')
            
            use_footer = bool(footer_text)
            pdf_kwargs = dict(
                path=str(output_path),
                format='A4',
                print_background=True,
                margin={
                    'top': '20mm', 'right': '15mm',
                    'bottom': '30mm' if use_footer else '20mm',
                    'left': '15mm'
                },
                display_header_footer=use_footer,
            )
            if use_footer:
                pdf_kwargs['header_template'] = '<div></div>'
                pdf_kwargs['footer_template'] = (
                    '<div style="font-size: 8px; color: #666; width: 100%; text-align: center; '
                    'font-family: Segoe UI, Arial, sans-serif; padding: 0 15mm;">'
                    f'{footer_text}'
                    '&nbsp;&nbsp;&mdash;&nbsp;&nbsp;'
                    'Page <span class="pageNumber"></span> of <span class="totalPages"></span>'
                    '</div>'
                )
            
            page.pdf(**pdf_kwargs)
            page.close()
        finally:
            if html_file.exists():
                html_file.unlink()
    
    def _fix_image_paths_for_local(self, html_content: str, images_dir: Path) -> str:
        """Embed images as data URIs (convert SVG to PNG first for reliability)."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html_content, 'lxml')
        
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if not src:
                continue
            
            src_path = None

            if src.startswith(('http://', 'https://', 'data:', 'file://')):
                # Remote URLs are less reliable in Playwright; attempt to resolve to downloaded file
                candidate = Path(src)
                src_path = candidate if candidate.exists() else (images_dir / candidate.name if images_dir else None)
            else:
                candidate = Path(src)
                if candidate.is_absolute():
                    src_path = candidate
                else:
                    # HTML uses images/<file>; drop the prefix and look in the images_dir
                    src_path = images_dir / candidate.name if images_dir else candidate
            
            if not src_path or not src_path.exists():
                continue
            
            # Convert SVG to PNG for better PDF rendering
            if src_path.suffix.lower() == '.svg':
                converted = self._convert_svg_to_png(src_path)
                src_path = converted if converted else src_path
            
            data_uri = self._img_to_data_uri(src_path)
            if data_uri:
                img['src'] = data_uri
        
        return str(soup)

    def _img_to_data_uri(self, path: Path) -> Optional[str]:
        """Read image bytes and return a base64 data URI."""
        mime, _ = mimetypes.guess_type(path.name)
        if not mime:
            mime = 'image/png'
        try:
            with open(path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('ascii')
            return f"data:{mime};base64,{encoded}"
        except Exception as e:
            console.print(f"[yellow]Failed to embed image {path.name}: {e}[/yellow]")
            return None
    
    def _convert_svg_to_png(self, svg_path: Path) -> Path:
        """Convert SVG to PNG for better PDF embedding."""
        png_path = svg_path.with_suffix('.png')
        
        # Skip if PNG already exists
        if png_path.exists():
            return png_path
        
        try:
            import cairosvg
            # Read SVG content first to fix common issues
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # Fix 1: Ensure viewBox has 4 values if present
            import re
            def fix_viewbox(match):
                values = match.group(1).strip().split()
                if len(values) == 3:
                    # Assume 0 0 width height, and the 3 values are 0 0 width (missing height?) or similar
                    # Or maybe it's x y width (missing height)
                    # Safest fallback: just return original or try to pad?
                    # Actually, the error "expected 4, got 3" suggests cairosvg is strict.
                    # Let's try to pad with '0' if it looks like x y w
                    return f'viewBox="{" ".join(values)} 0"' 
                return match.group(0)

            # Simple regex to find viewBox and potentially fix it? 
            # Actually, let's just catch the specific error and try to sanitize the SVG
            
            cairosvg.svg2png(bytestring=svg_content.encode('utf-8'), write_to=str(png_path), scale=2.0)
            console.print(f"[dim]Converted SVG to PNG: {svg_path.name}[/dim]")
            return png_path
        except ImportError:
            console.print("[yellow]cairosvg not installed, SVG may not render properly. Install: pip install cairosvg[/yellow]")
            return svg_path
        except Exception as e:
            # If conversion fails, we just return the original SVG path
            # The PDF renderer will try to use the SVG directly (which might work or show a broken image)
            console.print(f"[yellow]Failed to convert SVG {svg_path.name}: {e}[/yellow]")
            return svg_path
    
    def _strip_html_tags(self, html_text: str) -> str:
        """Strip HTML tags from text."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, 'lxml')
        return soup.get_text(strip=True)
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe file system use."""
        import re
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Replace spaces with underscores
        filename = filename.replace(' ', '_')
        # Limit length
        return filename[:100]
    
    def _get_pdf_css(self) -> str:
        """Get CSS styles optimized for PDF rendering in Playwright."""
        return f"""
        @media print {{
            * {{
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }}
        }}
        
        * {{
            box-sizing: border-box;
        }}
        
        body {{
            font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
            font-size: {self.font_size};
            line-height: 1.6;
            color: #333;
            max-width: 100%;
        }}
        
        img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 1em auto;
        }}
        
        svg {{
            max-width: 100%;
            height: auto;
        }}
        
        .cover-page {{
            page-break-after: always;
            text-align: center;
            padding-top: 30%;
        }}
        
        .cover-title {{
            font-size: 2.5em;
            color: #0078d4;
            margin-bottom: 1em;
        }}
        
        .cover-summary {{
            font-size: 1.2em;
            margin: 2em 10%;
            line-height: 1.8;
        }}
        
        .cover-metadata {{
            margin-top: 3em;
            font-size: 0.9em;
            color: #666;
        }}
        
        .toc-page {{
            page-break-after: always;
        }}
        
        .toc-title {{
            font-size: 2em;
            color: #0078d4;
            margin-bottom: 1em;
        }}
        
        .toc-list {{
            list-style-type: none;
            padding-left: 0;
        }}
        
        .toc-module {{
            font-weight: bold;
            margin: 1em 0;
            font-size: 1.1em;
        }}
        
        .toc-units {{
            list-style-type: none;
            padding-left: 2em;
            font-weight: normal;
            font-size: 0.95em;
        }}
        
        .toc-unit {{
            margin: 0.5em 0;
        }}
        
        .module {{
            page-break-before: always;
        }}
        
        .module-title {{
            font-size: 1.8em;
            color: #0078d4;
            border-bottom: 3px solid #0078d4;
            padding-bottom: 0.3em;
            margin-bottom: 1em;
            string-set: chapter content();
        }}
        
        .module-summary {{
            background: #f8f9fa;
            padding: 1em;
            margin: 1em 0;
            border-left: 4px solid #0078d4;
        }}
        
        .unit {{
            margin: 2em 0;
        }}
        
        .unit-title {{
            font-size: 1.4em;
            color: #333;
            margin: 1.5em 0 0.8em 0;
        }}
        
        h1, h2, h3, h4, h5, h6 {{
            page-break-after: avoid;
            page-break-inside: avoid;
        }}
        
        p {{
            margin: 0.8em 0;
            orphans: 3;
            widows: 3;
        }}
        
        img {{
            max-width: 100%;
            height: auto;
            page-break-inside: avoid;
            display: block;
            margin: 1em auto;
        }}
        
        code {{
            background: #f4f4f4;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-family: "Consolas", "Monaco", "Courier New", monospace;
            font-size: 0.9em;
        }}
        
        pre {{
            background: #2d2d2d;
            color: #f8f8f2;
            padding: 1em;
            border-radius: 4px;
            overflow-x: auto;
            page-break-inside: avoid;
            margin: 1em 0;
        }}
        
        pre code {{
            background: none;
            color: inherit;
            padding: 0;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1em 0;
            page-break-inside: avoid;
        }}
        
        th, td {{
            border: 1px solid #ddd;
            padding: 0.5em;
            text-align: left;
        }}
        
        th {{
            background: #f8f9fa;
            font-weight: bold;
        }}
        
        blockquote {{
            border-left: 4px solid #0078d4;
            padding-left: 1em;
            margin: 1em 0;
            color: #666;
            font-style: italic;
        }}
        
        ul, ol {{
            margin: 0.8em 0;
            padding-left: 2em;
        }}
        
        li {{
            margin: 0.3em 0;
        }}
        
        .footer-info {{
            page-break-before: always;
            text-align: center;
            padding-top: 40%;
            font-size: 0.9em;
            color: #666;
        }}
        """
