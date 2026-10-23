"""Main downloader orchestrator."""

import shutil
from pathlib import Path
from typing import Dict, List, Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .api_client import MSLearnAPIClient
from .content_scraper import ContentScraper
from .image_handler import ImageHandler
from .formatters import HTMLFormatter, MarkdownFormatter
from .pdf_formatter import PDFFormatter

console = Console()


class MSLearnDownloader:
    """Main downloader class that orchestrates the download process."""
    
    def __init__(self, config):
        """Initialize downloader with configuration."""
        self.config = config
        self.api_client = MSLearnAPIClient(config)
        self.content_scraper = ContentScraper(self.api_client)
        self.image_handler = ImageHandler(self.api_client, config)
    
    def download_course(self, course_url: str, output_format: str, output_dir: str,
                        filename_prefix: Optional[str] = None) -> bool:
        """Download all learning paths in a course."""
        learning_path_uids = self.content_scraper.scrape_course_learning_path_uids(course_url)
        
        if not learning_path_uids:
            console.print("[red]No learning paths found in this course[/red]")
            return False
            
        return self._download_course_paths(
            learning_path_uids,
            course_url.rstrip('/').split('/')[-1],
            output_format,
            output_dir,
            filename_prefix,
        )

    def download_course_by_uid(self, course_uid: str, output_format: str, output_dir: str,
                               filename_prefix: Optional[str] = None) -> bool:
        """Download a course by its UID."""
        # Fetch course details
        data = self.api_client.get_catalog(type='courses', uid=course_uid)
        courses = data.get('courses', [])
        if not courses:
            console.print(f"[red]Course not found: {course_uid}[/red]")
            return False
            
        course = courses[0]
        console.print(f"[green]Found course: {course.get('title')}[/green]")
        
        study_guide = course.get('study_guide', [])
        learning_path_uids = [item['uid'] for item in study_guide if item.get('type') == 'learningPath']
        
        if not learning_path_uids:
            console.print("[red]No learning paths found in this course[/red]")
            return False
            
        return self._download_course_paths(
            learning_path_uids, course_uid, output_format, output_dir, filename_prefix
        )

    def _download_course_paths(self, learning_path_uids: List[str], course_id: str,
                               output_format: str, output_dir: str,
                               filename_prefix: Optional[str] = None) -> bool:
        """Helper to download a list of learning paths for a course."""
        console.print(f"[green]Found {len(learning_path_uids)} learning paths in course[/green]")
        
        # Create course subfolder
        import os
        course_output_dir = os.path.join(output_dir, course_id)
        
        success_count = 0
        for i, uid in enumerate(learning_path_uids, 1):
            console.print(f"\n[bold]Processing learning path {i}/{len(learning_path_uids)}: {uid}[/bold]")
            # Recursively call download_learning_path for each path
            if self.download_learning_path(
                learning_path_uid=uid,
                output_format=output_format,
                output_dir=course_output_dir,
                filename_prefix=filename_prefix,
            ):
                success_count += 1
                
        console.print(f"\n[green]Course download complete. {success_count}/{len(learning_path_uids)} learning paths downloaded successfully.[/green]")
        console.print(f"Location: {course_output_dir}")
        return success_count > 0

    def download_exam(self, url: str, output_format: str, output_dir: str) -> bool:
        """Download an exam's study guide: one subfolder per learning path, one file per module."""
        exam = self.api_client.get_exam_learning_paths(url)
        if not exam:
            return False

        paths = exam['learning_paths']
        console.print(f"[green]Found {len(paths)} learning paths in: {exam['title']}[/green]")

        width = max(2, len(str(len(paths))))
        success_count = 0
        for i, path in enumerate(paths, 1):
            console.print(f"\n[bold]Processing learning path {i}/{len(paths)}: {path['title']}[/bold]")
            folder = f"{i:0{width}d} - {self._safe_folder_name(path['title'])}"
            try:
                if self.download_learning_path_modules(
                    path['uid'], output_format, str(Path(output_dir) / folder)
                ):
                    success_count += 1
            except Exception as e:
                console.print(f"[red]Failed to download {path['uid']}: {e}[/red]")

        console.print(f"\n[green]Exam download complete. {success_count}/{len(paths)} learning paths downloaded successfully.[/green]")
        return success_count > 0

    def _split_formats(self, output_format: str):
        """Return (combined_html_format, per_module_formats).

        HTML is a single combined file unless output.html_split_modules is set;
        every other format is always written per module.
        """
        formats = output_format.split(',') if output_format != 'all' else ['html', 'markdown', 'pdf']
        formats = [f.strip() for f in formats if f.strip()]
        if 'html' in formats and not self.config.get('output.html_split_modules', False):
            rest = [f for f in formats if f != 'html']
            return 'html', (','.join(rest) or None)
        return None, ','.join(formats)

    def download_learning_path_modules(self, learning_path_uid: str, output_format: str,
                                       output_dir: str, filename_prefix: Optional[str] = None) -> bool:
        """Download a learning path as one numbered file per module in output_dir.

        HTML is written as a single combined file (named with filename_prefix) unless
        output.html_split_modules is enabled.
        """
        combined_fmt, split_fmt = self._split_formats(output_format)
        success = False

        if combined_fmt:
            success = bool(self.download_learning_path(
                learning_path_uid=learning_path_uid,
                output_format=combined_fmt,
                output_dir=output_dir,
                filename_prefix=filename_prefix,
            ))
        if not split_fmt:
            return success

        learning_path = self.api_client.get_learning_path_by_uid(learning_path_uid)
        if not learning_path:
            return success

        modules = self.api_client.get_modules_for_learning_path(learning_path)
        if not modules:
            console.print("[red]No modules found for this learning path[/red]")
            return success

        width = max(2, len(str(len(modules))))
        success_count = 0
        for i, module in enumerate(modules, 1):
            console.print(f"\n[bold]Module {i}/{len(modules)}: {module.get('title')}[/bold]")
            try:
                if self.download_module(module['uid'], split_fmt, output_dir,
                                        filename_prefix=f"{i:0{width}d}"):
                    success_count += 1
            except Exception as e:
                console.print(f"[red]Failed to download {module['uid']}: {e}[/red]")

        console.print(f"[green]{success_count}/{len(modules)} modules downloaded to {output_dir}[/green]")
        return success or success_count > 0

    @staticmethod
    def _safe_folder_name(name: str) -> str:
        """Make a title safe to use as a folder name on Windows and other platforms."""
        import re
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name or '').strip(' .')
        return name[:100].rstrip(' .') or 'untitled'

    def download_renewal_collection(self, url: str, output_format: str, output_dir: str,
                                    filename_prefix: Optional[str] = None) -> bool:
        """Download every module in a certification renewal page, in page order."""
        collection = self.api_client.get_renewal_collection(url)
        if not collection:
            return False

        modules = collection['modules']
        console.print(f"[green]Found {len(modules)} modules in: {collection['title']}[/green]")

        combined_fmt, split_fmt = self._split_formats(output_format)
        combined_ok = False
        if combined_fmt:
            combined_ok = self._download_modules_combined(
                collection, [m['uid'] for m in modules], combined_fmt, output_dir
            )
        if not split_fmt:
            return combined_ok

        width = max(2, len(str(len(modules))))
        success_count = 0
        for i, module in enumerate(modules, 1):
            console.print(f"\n[bold]Processing module {i}/{len(modules)}: {module['title']}[/bold]")
            prefix = f"{i:0{width}d}"
            try:
                if self.download_module(module['uid'], split_fmt, output_dir, filename_prefix=prefix):
                    success_count += 1
            except Exception as e:
                console.print(f"[red]Failed to download {module['uid']}: {e}[/red]")

        console.print(f"\n[green]Collection download complete. {success_count}/{len(modules)} modules downloaded successfully.[/green]")
        return combined_ok or success_count > 0

    def _download_modules_combined(self, info: Dict, module_uids: list, output_format: str,
                                   output_dir: str) -> bool:
        """Scrape several modules and save them together as one document."""
        modules_content = []
        all_images = []
        module_infos = []
        for uid in module_uids:
            scraped = self._scrape_module(uid)
            if not scraped:
                continue
            module, module_data = scraped
            module_infos.append(module)
            modules_content.append(module_data)
            all_images.extend(module_data.get('images', []))

        if not modules_content:
            return False

        self._process_images(all_images, modules_content, output_dir)
        combined = {
            'uid': info.get('uid'),
            'title': info.get('title'),
            'summary': info.get('summary', ''),
            'url': info.get('url'),
            'modules': module_infos,
        }
        self._save_output(combined, modules_content, output_format, output_dir)
        return True

    def _scrape_module(self, module_uid: str):
        """Fetch and scrape one module. Returns (module, scraped_data) or None."""
        data = self.api_client.get_catalog(type='modules', uid=module_uid)
        modules = data.get('modules', [])
        if not modules:
            console.print(f"[red]Module not found: {module_uid}[/red]")
            return None

        module = modules[0]
        console.print(f"[green]Found module: {module.get('title')}[/green]")
        units = self.api_client.get_units_for_modules([module]).get(module_uid, [])
        if not units:
            console.print("[red]No units found for this module[/red]")
            return None

        return module, self.content_scraper.scrape_module_content(module, units)

    def download_module(self, module_uid: str, output_format: str, output_dir: str,
                        filename_prefix: Optional[str] = None) -> bool:
        """Download a single module by UID."""
        # Fetch module details
        data = self.api_client.get_catalog(type='modules', uid=module_uid)
        modules = data.get('modules', [])
        if not modules:
            console.print(f"[red]Module not found: {module_uid}[/red]")
            return False
            
        module = modules[0]
        console.print(f"[green]Found module: {module.get('title')}[/green]")
        
        # Get units for module
        units_by_module = self.api_client.get_units_for_modules([module])
        units = units_by_module.get(module_uid, [])
        
        if not units:
            console.print("[red]No units found for this module[/red]")
            return False
            
        # Scrape content
        modules_content = []
        all_images = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Downloading content...", total=1)
            
            module_data = self.content_scraper.scrape_module_content(module, units)
            modules_content.append(module_data)
            all_images.extend(module_data.get('images', []))
            
            progress.advance(task)
            
        # Download images if enabled
        self._process_images(all_images, modules_content, output_dir)
        
        # Format and save output
        # Wrap in a dummy learning path structure for the formatters
        dummy_lp = {
            'uid': module_uid,
            'title': module.get('title'),
            'summary': module.get('summary'),
            'url': module.get('url'),
            'modules': [module]
        }
        
        self._save_output(dummy_lp, modules_content, output_format, output_dir, filename_prefix)
        return True

    def _process_images(self, all_images, modules_content, output_dir):
        """Helper to download and update images."""
        if self.config.get('download.images', True) and all_images:
            output_path = Path(output_dir or self.config.get('storage.output_dir', './downloads'))
            image_url_mapping = self.image_handler.download_images(all_images, output_path)
            
            # Update image paths in content
            for module_data in modules_content:
                for unit_data in module_data['content']:
                    unit_data['html'] = self.image_handler.update_html_image_paths(
                        unit_data['html'], 
                        image_url_mapping,
                        relative_to=output_path,
                        images_subdir='images'
                    )

    def _save_output(self, learning_path, modules_content, output_format, output_dir,
                     filename_prefix: Optional[str] = None):
        """Helper to save output in requested formats."""
        output_path = Path(output_dir or self.config.get('storage.output_dir', './downloads'))
        formats = output_format.split(',') if output_format != 'all' else ['html', 'markdown', 'pdf']
        
        if 'html' in formats:
            formatter = HTMLFormatter(self.config)
            formatter.format(learning_path, modules_content, output_path, filename_prefix=filename_prefix)
            
        if 'markdown' in formats or 'md' in formats:
            formatter = MarkdownFormatter(self.config)
            formatter.format(learning_path, modules_content, output_path, filename_prefix=filename_prefix)
            
        if 'pdf' in formats:
            formatter = PDFFormatter(self.config)
            images_dir = output_path / "images"
            formatter.format(
                learning_path,
                modules_content,
                output_path,
                images_dir if images_dir.exists() else None,
                filename_prefix,
            )

        # Cleanup downloaded images if requested (after all formats are generated)
        if self.config.get('cleanup.delete_images', False):
            images_dir = output_path / "images"
            if images_dir.exists():
                console.print("[dim]Cleaning up images folder...[/dim]")
                shutil.rmtree(images_dir)

    def download_learning_path(self, learning_path_uid: str = None, learning_path_url: str = None,
                               output_format: str = 'pdf', output_dir: str = None,
                               filename_prefix: Optional[str] = None) -> bool:
        """Download a learning path by UID or URL."""
        
        # Check if it's a certification exam page URL
        if learning_path_url and self.api_client.is_exam_url(learning_path_url):
            return self.download_exam(learning_path_url, output_format, output_dir)

        # Check if it's a certification renewal collection URL
        if learning_path_url and self.api_client.is_renewal_url(learning_path_url):
            return self.download_renewal_collection(
                learning_path_url, output_format, output_dir, filename_prefix
            )

        # Check if it's a course URL
        if learning_path_url and '/courses/' in learning_path_url:
            return self.download_course(
                learning_path_url, output_format, output_dir, filename_prefix
            )
        
        # Get learning path metadata
        if learning_path_uid:
            learning_path = self.api_client.get_learning_path_by_uid(learning_path_uid)
        elif learning_path_url:
            learning_path = self.api_client.get_learning_path_from_url(learning_path_url)
        else:
            console.print("[red]Please provide either a UID or URL[/red]")
            return False
        
        if not learning_path:
            return False
        
        console.print(f"[green]Found learning path: {learning_path.get('title')}[/green]")
        console.print(f"Modules: {learning_path.get('number_of_children', 0)}")
        console.print(f"Duration: {learning_path.get('duration_in_minutes', 0)} minutes")
        console.print()
        
        # Get modules
        modules = self.api_client.get_modules_for_learning_path(learning_path)
        if not modules:
            console.print("[red]No modules found for this learning path[/red]")
            return False
        
        # Get units for all modules
        units_by_module = self.api_client.get_units_for_modules(modules)
        
        # Scrape content for each module
        modules_content = []
        all_images = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Downloading content...", total=len(modules))
            
            for module in modules:
                module_uid = module['uid']
                units = units_by_module.get(module_uid, [])
                
                if units:
                    module_data = self.content_scraper.scrape_module_content(module, units)
                    modules_content.append(module_data)
                    all_images.extend(module_data.get('images', []))
                
                progress.advance(task)
        
        # Download images and save output
        self._process_images(all_images, modules_content, output_dir)
        self._save_output(
            learning_path, modules_content, output_format, output_dir, filename_prefix
        )
        
        return True
