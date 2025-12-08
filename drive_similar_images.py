"""
Google Drive Similar Image Finder
Uses perceptual hashing to find visually similar images
"""
import logging
import io
import os
from typing import List, Dict, Set, Tuple
from collections import defaultdict
from pathlib import Path
from PIL import Image
import imagehash
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from auth import get_credentials
from config import IMAGE_MIMETYPES, SIMILARITY_THRESHOLD, DUPLICATES_DUMP_DIR
from tqdm import tqdm

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


class SimilarImageFinder:
    """Find visually similar images using perceptual hashing."""
    
    def __init__(self, similarity_threshold: float = SIMILARITY_THRESHOLD):
        """
        Initialize finder.
        
        Args:
            similarity_threshold: 0.0-1.0, higher = stricter (0.95 = 95% similar)
        """
        self.service = build('drive', 'v3', credentials=get_credentials())
        self.similarity_threshold = similarity_threshold
        self.image_hashes = {}
    
    def list_all_images(self, page_size: int = 100) -> List[Dict]:
        """
        List all image files in Drive.
        
        Args:
            page_size: Number of files per page
        
        Returns:
            List of image file metadata
        """
        files = []
        page_token = None
        
        # Build query for images you own
        mime_query = " or ".join([f"mimeType='{mime}'" for mime in IMAGE_MIMETYPES])
        query = f"trashed=false and ({mime_query}) and 'me' in owners"
        
        print("📸 Scanning Google Drive for images...")
        
        try:
            while True:
                response = self.service.files().list(
                    q=query,
                    pageSize=page_size,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, webViewLink)"
                ).execute()
                
                batch = response.get('files', [])
                files.extend(batch)
                
                print(f"   Found {len(files)} images...", end='\r')
                
                page_token = response.get('nextPageToken')
                if not page_token:
                    break
        
        except HttpError as e:
            logger.error(f"HTTP Error listing images: {e}")
        except Exception as e:
            logger.error(f"Error listing images: {e}")
        
        print(f"\n✅ Total images found: {len(files)}")
        return files
    
    def download_image_for_hashing(self, file_id: str) -> Image.Image:
        """
        Download image from Drive for hash computation.
        
        Args:
            file_id: Google Drive file ID
        
        Returns:
            PIL Image object or None if error
        """
        try:
            request = self.service.files().get_media(fileId=file_id)
            
            # Download to bytes
            file_bytes = io.BytesIO()
            downloader = MediaIoBaseDownload(file_bytes, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            # Load as PIL Image
            file_bytes.seek(0)
            image = Image.open(file_bytes)
            return image
        
        except Exception as e:
            logger.error(f"Error downloading image {file_id}: {e}")
            return None
    
    def compute_image_hash(self, image: Image.Image) -> str:
        """
        Compute perceptual hash of image.
        
        Args:
            image: PIL Image object
        
        Returns:
            Hash string
        """
        try:
            # Use average hash (fast and robust)
            hash_value = imagehash.average_hash(image, hash_size=8)
            return str(hash_value)
        except Exception as e:
            logger.error(f"Error computing hash: {e}")
            return None
    
    def compute_hashes_for_images(self, files: List[Dict]) -> Dict[str, str]:
        """
        Compute perceptual hashes for all images.
        
        Args:
            files: List of image file metadata
        
        Returns:
            Dictionary mapping file_id to hash
        """
        print("🔍 Computing perceptual hashes...")
        
        hashes = {}
        failed = 0
        
        pbar = tqdm(files, desc="Hashing images", ncols=80, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for file in pbar:
            file_id = file['id']
            
            image = self.download_image_for_hashing(file_id)
            
            if image:
                hash_value = self.compute_image_hash(image)
                if hash_value:
                    hashes[file_id] = hash_value
                else:
                    failed += 1
            else:
                failed += 1
        
        pbar.close()
        print(f"✅ Hashed {len(hashes)}/{len(files)} images")
        if failed:
            print(f"⚠️  Failed to hash {failed} images")
        
        return hashes
    
    def find_similar_images(self, files: List[Dict], hashes: Dict[str, str]) -> Dict[str, List[Dict]]:
        """
        Find groups of similar images.
        
        Args:
            files: List of image file metadata
            hashes: Dictionary of file_id -> hash
        
        Returns:
            Dictionary mapping representative file_id to list of similar files
        """
        print("🔍 Finding similar images...")
        
        file_lookup = {f['id']: f for f in files}
        similar_groups = defaultdict(list)
        processed = set()
        
        file_ids = list(hashes.keys())
        
        pbar = tqdm(file_ids, desc="Comparing", ncols=80, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for i, file_id_1 in enumerate(pbar):
            if file_id_1 in processed:
                continue
            
            hash_1 = imagehash.hex_to_hash(hashes[file_id_1])
            group = [file_lookup[file_id_1]]
            processed.add(file_id_1)
            
            for file_id_2 in file_ids[i+1:]:
                if file_id_2 in processed:
                    continue
                
                hash_2 = imagehash.hex_to_hash(hashes[file_id_2])
                
                # Calculate similarity (0 = identical, higher = more different)
                difference = hash_1 - hash_2
                max_difference = 64
                similarity = 1.0 - (difference / max_difference)
                
                if similarity >= self.similarity_threshold:
                    group.append(file_lookup[file_id_2])
                    processed.add(file_id_2)
            
            if len(group) > 1:
                similar_groups[file_id_1] = group
        
        pbar.close()
        print(f"✅ Found {len(similar_groups)} groups of similar images")
        
        return dict(similar_groups)
    
    def calculate_wasted_space(self, similar_groups: Dict[str, List[Dict]]) -> Dict:
        """Calculate space wasted by similar images."""
        total_wasted_bytes = 0
        total_similar_files = 0
        groups_info = []
        
        for group_id, files in similar_groups.items():
            total_group_size = sum(int(f.get('size', 0)) for f in files)
            files_sorted = sorted(files, key=lambda x: int(x.get('size', 0)), reverse=True)
            keeper_size = int(files_sorted[0].get('size', 0))
            wasted_size = total_group_size - keeper_size
            
            total_wasted_bytes += wasted_size
            total_similar_files += len(files)
            
            groups_info.append({
                'keeper': files_sorted[0],
                'similar_files': files_sorted[1:],
                'num_similar': len(files),
                'total_size_mb': total_group_size / (1024 * 1024),
                'keeper_size_mb': keeper_size / (1024 * 1024),
                'wasted_mb': wasted_size / (1024 * 1024),
                'files': files_sorted,
                'hash': list(similar_groups.keys())[list(similar_groups.values()).index(files)]
            })
        
        groups_info.sort(key=lambda x: x['wasted_mb'], reverse=True)
        
        return {
            'total_similar_files': total_similar_files,
            'total_groups': len(similar_groups),
            'total_wasted_mb': total_wasted_bytes / (1024 * 1024),
            'total_wasted_gb': total_wasted_bytes / (1024 * 1024 * 1024),
            'similar_groups': groups_info
        }
    
    def download_file(self, file_id: str, destination: str, file_name: str = None) -> bool:
        """Download a file from Drive (silent)."""
        try:
            request = self.service.files().get_media(fileId=file_id)
            
            with io.FileIO(destination, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
            
            return True
        
        except Exception as e:
            logger.error(f"Error downloading {file_name or file_id}: {e}")
            return False
    
    def delete_file(self, file_id: str) -> bool:
        """Delete a file from Drive."""
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except Exception as e:
            return False
    
    def dump_and_delete_similar(self, similar_group: Dict, keep_index: int = 0) -> Dict:
        """
        Download similar images locally, then DELETE from Drive.
        
        Args:
            similar_group: Group of similar images
            keep_index: Index of file to keep (default: 0 = largest/best quality)
        
        Returns:
            Results of dump+delete operation
        """
        files = similar_group['files']
        keeper = files[keep_index]
        
        # Create subfolder for this similar group
        group_name = keeper['name'].split('.')[0][:30]  # Use keeper's name
        dump_folder = DUPLICATES_DUMP_DIR / f"similar_{group_name}"
        dump_folder.mkdir(exist_ok=True)
        
        downloaded = []
        deleted_from_drive = []
        failed = []
        skipped_no_permission = []
        
        for i, file in enumerate(files):
            if i == keep_index:
                # Keep this one (largest/best quality)
                continue
            
            file_id = file['id']
            file_name = file['name']
            file_size = int(file.get('size', 0))
            
            # Create unique filename
            name_parts = os.path.splitext(file_name)
            local_filename = f"{name_parts[0]}_similar{i+1}{name_parts[1]}"
            local_path = dump_folder / local_filename
            
            # Download
            if self.download_file(file_id, str(local_path), file_name):
                downloaded.append({
                    'id': file_id,
                    'name': file_name,
                    'size': file_size,
                    'local_path': str(local_path),
                    'created': file.get('createdTime', 'Unknown')[:10]
                })
                
                # Delete from Drive
                if self.delete_file(file_id):
                    deleted_from_drive.append(file_id)
                else:
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
        
        # Create README
        readme_path = dump_folder / 'README.txt'
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(f"Similar Images Group: {keeper['name']}\n")
            f.write(f"Similarity Threshold: {self.similarity_threshold * 100:.0f}%\n")
            f.write(f"Total Similar Images: {len(files)}\n")
            f.write(f"Space Recovered: {similar_group['wasted_mb']:.2f} MB\n\n")
            f.write(f"Processed: {len(files)} files\n")
            f.write(f"Downloaded: {len(downloaded)} files\n")
            f.write(f"Deleted from Drive: {len(deleted_from_drive)} files\n")
            f.write(f"Kept in Drive: 1 file (best quality)\n")
            f.write(f"Skipped (no permission): {len(skipped_no_permission)} files\n")
            f.write(f"Failed: {len(failed)} files\n\n")
            f.write("=" * 70 + "\n")
            f.write("Files:\n")
            f.write("=" * 70 + "\n\n")
            for i, file in enumerate(files, 1):
                if i-1 == keep_index:
                    status = "✅ KEPT IN DRIVE (Best Quality)"
                elif file['id'] in deleted_from_drive:
                    status = "🗑️  DOWNLOADED & DELETED FROM DRIVE"
                elif any(s['id'] == file['id'] for s in skipped_no_permission):
                    status = "⚠️  SKIPPED (No permission)"
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
        """Generate human-readable report."""
        report = []
        report.append("=" * 70)
        report.append("📸 GOOGLE DRIVE SIMILAR IMAGE REPORT")
        report.append("=" * 70)
        report.append("")
        report.append("📈 SUMMARY")
        report.append(f"   Total similar files: {stats['total_similar_files']:,}")
        report.append(f"   Similar groups: {stats['total_groups']:,}")
        report.append(f"   Wasted space: {stats['total_wasted_gb']:.2f} GB ({stats['total_wasted_mb']:.1f} MB)")
        report.append(f"   Similarity threshold: {self.similarity_threshold * 100:.0f}%")
        report.append("")
        report.append(f"🔝 TOP {top_n} SIMILAR IMAGE GROUPS")
        report.append("-" * 70)
        
        for i, group in enumerate(stats['similar_groups'][:top_n], 1):
            keeper = group['keeper']
            report.append(f"{i}. {keeper['name']} (KEEP)")
            report.append(f"   Size: {group['keeper_size_mb']:.2f} MB")
            report.append(f"   Similar images: {group['num_similar'] - 1}")
            report.append(f"   Wasted space: {group['wasted_mb']:.2f} MB")
            report.append(f"   Files:")
            report.append(f"     ✓ {keeper['name']} (KEEPER - {group['keeper_size_mb']:.2f} MB)")
            for similar_file in group['similar_files']:
                size_mb = int(similar_file.get('size', 0)) / (1024 * 1024)
                report.append(f"     ✗ {similar_file['name']} ({size_mb:.2f} MB)")
            report.append("")
        
        report.append("=" * 70)
        return "\n".join(report)


# CLI Test
if __name__ == "__main__":
    print("=" * 70)
    print("📸 Google Drive Similar Image Finder")
    print("=" * 70)
    print()
    
    finder = SimilarImageFinder(similarity_threshold=0.90)
    
    images = finder.list_all_images()
    
    if not images:
        print("\n❌ No images found in Drive")
        exit(1)
    
    # Limit for testing
    if len(images) > 50:
        print(f"\n⚠️  Found {len(images)} images. Testing with first 50...")
        images = images[:50]
    
    hashes = finder.compute_hashes_for_images(images)
    
    if not hashes:
        print("\n❌ Failed to compute hashes")
        exit(1)
    
    similar_groups = finder.find_similar_images(images, hashes)
    
    if not similar_groups:
        print("\n✅ No similar images found!")
        exit(0)
    
    stats = finder.calculate_wasted_space(similar_groups)
    report = finder.generate_report(stats)
    print(report)
    
    report_file = 'similar_images_report.txt'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n💾 Report saved to: {report_file}")
    print()
    print("=" * 70)