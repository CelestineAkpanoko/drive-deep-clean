"""
Google Drive Duplicate File Finder
Uses MD5 hashing to identify exact duplicates
"""
import logging
import os
from typing import List, Dict, Set
from collections import defaultdict
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from auth import get_credentials
from config import IMAGE_MIMETYPES, VIDEO_MIMETYPES, DOCUMENT_MIMETYPES, DUPLICATES_DUMP_DIR
from tqdm import tqdm
import io

logging.basicConfig(level=logging.ERROR)  # Suppress warnings
logger = logging.getLogger(__name__)


class DriveDuplicateFinder:
    """Find and manage duplicate files in Google Drive."""
    
    def __init__(self):
        self.service = build('drive', 'v3', credentials=get_credentials())
        self.files_by_hash = defaultdict(list)
        self.total_files = 0
        self.total_size = 0
    
    def list_all_files(self, page_size: int = 100) -> List[Dict]:
        """
        List all files in Drive with MD5 checksums.
        
        Args:
            page_size: Number of files per page
        
        Returns:
            List of file metadata dictionaries
        """
        files = []
        page_token = None
        
        # Query for files with MD5 hash + files you own
        query = "trashed=false and mimeType != 'application/vnd.google-apps.folder' and 'me' in owners"
        
        print("📁 Scanning Google Drive for files you own...")
        
        try:
            while True:
                response = self.service.files().list(
                    q=query,
                    pageSize=page_size,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name, mimeType, size, md5Checksum, createdTime, modifiedTime, parents, webViewLink, ownedByMe)"
                ).execute()
                
                batch = response.get('files', [])
                files.extend(batch)
                
                print(f"   Found {len(files)} files...", end='\r')
                
                page_token = response.get('nextPageToken')
                if not page_token:
                    break
        
        except HttpError as e:
            logger.error(f"HTTP Error listing files: {e}")
        except Exception as e:
            logger.error(f"Error listing files: {e}")
        
        print(f"\n✅ Total files found: {len(files)}")
        return files
    
    def find_duplicates(self, files: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Find duplicate files by MD5 hash.
        
        Args:
            files: List of file metadata from Drive
        
        Returns:
            Dictionary mapping MD5 hash to list of duplicate files
        """
        print("🔍 Analyzing files for duplicates...")
        
        hash_map = defaultdict(list)
        files_without_hash = 0
        
        pbar = tqdm(files, desc="Processing", ncols=80, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for file in pbar:
            md5 = file.get('md5Checksum')
            
            if md5:
                hash_map[md5].append(file)
            else:
                files_without_hash += 1
        
        # Filter to only duplicates (hash appears more than once)
        duplicates = {
            hash_val: file_list 
            for hash_val, file_list in hash_map.items() 
            if len(file_list) > 1
        }
        
        print(f"✅ Found {len(duplicates)} groups of duplicates")
        if files_without_hash:
            print(f"   Note: {files_without_hash} files without MD5 (Google Docs, Sheets, etc.)")
        
        return duplicates
    
    def calculate_wasted_space(self, duplicates: Dict[str, List[Dict]]) -> Dict:
        """
        Calculate space wasted by duplicates.
        
        Args:
            duplicates: Dictionary of duplicate file groups
        
        Returns:
            Statistics about wasted space
        """
        total_wasted_bytes = 0
        total_duplicate_files = 0
        duplicate_groups = []
        
        for md5_hash, file_group in duplicates.items():
            # Get file size (all duplicates have same size)
            file_size = int(file_group[0].get('size', 0))
            
            if file_size == 0:
                continue
            
            # Count duplicates (keep one, rest are wasted)
            num_duplicates = len(file_group)
            wasted_size = file_size * (num_duplicates - 1)
            
            total_wasted_bytes += wasted_size
            total_duplicate_files += num_duplicates
            
            duplicate_groups.append({
                'filename': file_group[0].get('name'),
                'mime_type': file_group[0].get('mimeType'),
                'file_size_bytes': file_size,
                'file_size_mb': file_size / (1024 * 1024),
                'num_copies': num_duplicates,
                'wasted_bytes': wasted_size,
                'wasted_mb': wasted_size / (1024 * 1024),
                'files': file_group,
                'md5': md5_hash
            })
        
        # Sort by wasted space (biggest impact first)
        duplicate_groups.sort(key=lambda x: x['wasted_bytes'], reverse=True)
        
        return {
            'total_duplicate_files': total_duplicate_files,
            'total_duplicate_groups': len(duplicates),
            'total_wasted_bytes': total_wasted_bytes,
            'total_wasted_mb': total_wasted_bytes / (1024 * 1024),
            'total_wasted_gb': total_wasted_bytes / (1024 * 1024 * 1024),
            'duplicate_groups': duplicate_groups
        }
    
    def download_file(self, file_id: str, destination: str, file_name: str = None) -> bool:
        """
        Download a file from Drive (silent, no progress bar).
        
        Args:
            file_id: Google Drive file ID
            destination: Local file path
            file_name: Optional file name for error logging
        
        Returns:
            True if successful, False otherwise
        """
        try:
            request = self.service.files().get_media(fileId=file_id)
            
            with io.FileIO(destination, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
            
            return True
        
        except HttpError as e:
            logger.error(f"Error downloading {file_name or file_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error downloading {file_name or file_id}: {e}")
            return False
    
    def delete_file(self, file_id: str) -> bool:
        """
        Delete a file from Drive.
        
        Args:
            file_id: Google Drive file ID
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except HttpError as e:
            # Silently fail on permission errors
            return False
        except Exception as e:
            return False
    
    def dump_and_delete_duplicates(self, duplicate_group: Dict, keep_index: int = 0) -> Dict:
        """
        Download duplicate files locally, then DELETE from Drive.
        
        IMPORTANT: This DELETES files from Drive after downloading!
        
        Args:
            duplicate_group: Group of duplicate files
            keep_index: Index of file to keep in Drive (default: 0 = keep first/oldest)
        
        Returns:
            Results of dump+delete operation
        """
        files = duplicate_group['files']
        md5 = duplicate_group['md5']
        base_filename = duplicate_group['filename']
        
        # Create subfolder for this duplicate group
        dump_folder = DUPLICATES_DUMP_DIR / md5[:8]
        dump_folder.mkdir(exist_ok=True)
        
        downloaded = []
        deleted_from_drive = []
        failed = []
        skipped_no_permission = []
        
        for i, file in enumerate(files):
            file_id = file['id']
            file_name = file['name']
            file_size = int(file.get('size', 0))
            
            if i == keep_index:
                # Keep this one in Drive
                continue
            
            # Add index to filename to avoid overwrites
            name_parts = os.path.splitext(file_name)
            local_filename = f"{name_parts[0]}_copy{i+1}{name_parts[1]}"
            local_path = dump_folder / local_filename
            
            # Download (silent)
            if self.download_file(file_id, str(local_path), file_name):
                downloaded.append({
                    'id': file_id,
                    'name': file_name,
                    'size': file_size,
                    'local_path': str(local_path),
                    'created': file.get('createdTime', 'Unknown')[:10]
                })
                
                # Delete from Drive after successful download
                if self.delete_file(file_id):
                    deleted_from_drive.append(file_id)
                else:
                    # Permission error - file is shared/not owned
                    skipped_no_permission.append({
                        'id': file_id,
                        'name': file_name,
                        'reason': 'no_permission'
                    })
            else:
                failed.append({
                    'id': file_id,
                    'name': file_name,
                    'reason': 'download_failed'
                })
        
        # Create README in dump folder
        readme_path = dump_folder / 'README.txt'
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(f"Duplicate Files: {base_filename}\n")
            f.write(f"MD5 Hash: {md5}\n")
            f.write(f"File Size: {duplicate_group['file_size_mb']:.2f} MB each\n")
            f.write(f"Total Copies: {duplicate_group['num_copies']}\n")
            f.write(f"Wasted Space Recovered: {duplicate_group['wasted_mb']:.2f} MB\n")
            f.write(f"\nProcessed: {len(files)} files\n")
            f.write(f"Downloaded: {len(downloaded)} files\n")
            f.write(f"Deleted from Drive: {len(deleted_from_drive)} files\n")
            f.write(f"Kept in Drive: 1 file\n")
            f.write(f"Skipped (no permission): {len(skipped_no_permission)} files\n")
            f.write(f"Failed: {len(failed)} files\n\n")
            f.write("=" * 70 + "\n")
            f.write("Files:\n")
            f.write("=" * 70 + "\n\n")
            for i, file in enumerate(files, 1):
                if i-1 == keep_index:
                    status = "✅ KEPT IN DRIVE"
                elif file['id'] in deleted_from_drive:
                    status = "🗑️  DOWNLOADED & DELETED FROM DRIVE"
                elif any(s['id'] == file['id'] for s in skipped_no_permission):
                    status = "⚠️  SKIPPED (No permission - shared file)"
                else:
                    status = "❌ FAILED"
                
                f.write(f"{i}. {file['name']} ({status})\n")
                f.write(f"   ID: {file['id']}\n")
                f.write(f"   Size: {int(file.get('size', 0)) / (1024 * 1024):.2f} MB\n")
                f.write(f"   Created: {file.get('createdTime', 'Unknown')[:10]}\n")
                f.write(f"   Link: {file.get('webViewLink', 'N/A')}\n\n")
        
        return {
            'downloaded': downloaded,
            'deleted_from_drive': deleted_from_drive,
            'skipped_no_permission': skipped_no_permission,
            'failed': failed,
            'dump_folder': str(dump_folder),
            'space_freed_bytes': sum(d['size'] for d in downloaded if d['id'] in deleted_from_drive),
            'space_freed_mb': sum(d['size'] for d in downloaded if d['id'] in deleted_from_drive) / (1024 * 1024)
        }
    
    def generate_report(self, stats: Dict, top_n: int = 20) -> str:
        """
        Generate a human-readable report of duplicates.
        
        Args:
            stats: Statistics from calculate_wasted_space()
            top_n: Number of top duplicates to show
        
        Returns:
            Formatted report string
        """
        report = []
        report.append("=" * 70)
        report.append("📊 GOOGLE DRIVE DUPLICATE FILE REPORT")
        report.append("=" * 70)
        report.append("")
        
        # Summary
        report.append("📈 SUMMARY")
        report.append(f"   Total duplicate files: {stats['total_duplicate_files']:,}")
        report.append(f"   Duplicate groups: {stats['total_duplicate_groups']:,}")
        report.append(f"   Wasted space: {stats['total_wasted_gb']:.2f} GB ({stats['total_wasted_mb']:.1f} MB)")
        report.append("")
        
        # Top duplicates
        report.append(f"🔝 TOP {top_n} SPACE WASTERS")
        report.append("-" * 70)
        
        for i, group in enumerate(stats['duplicate_groups'][:top_n], 1):
            report.append(f"{i}. {group['filename']}")
            report.append(f"   Type: {group['mime_type']}")
            report.append(f"   Size: {group['file_size_mb']:.2f} MB each")
            report.append(f"   Copies: {group['num_copies']}")
            report.append(f"   Wasted: {group['wasted_mb']:.2f} MB")
            report.append(f"   Files:")
            for j, file in enumerate(group['files'], 1):
                created = file.get('createdTime', 'Unknown')[:10]
                report.append(f"     {j}. ID: {file['id']} (Created: {created})")
            report.append("")
        
        report.append("=" * 70)
        
        return "\n".join(report)


# CLI Test
if __name__ == "__main__":
    print("=" * 70)
    print("🔍 Google Drive Duplicate Finder")
    print("=" * 70)
    print()
    
    finder = DriveDuplicateFinder()
    
    # Scan Drive
    files = finder.list_all_files()
    
    if not files:
        print("\n❌ No files found in Drive")
        exit(1)
    
    # Find duplicates
    duplicates = finder.find_duplicates(files)
    
    if not duplicates:
        print("\n✅ No duplicates found! Your Drive is clean.")
        exit(0)
    
    # Calculate stats
    stats = finder.calculate_wasted_space(duplicates)
    
    # Generate report
    report = finder.generate_report(stats)
    print(report)
    
    # Save report to file
    report_file = 'duplicate_report.txt'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n💾 Report saved to: {report_file}")
    print()
    print("=" * 70)