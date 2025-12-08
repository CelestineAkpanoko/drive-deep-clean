"""
Gmail Attachment Scanner and Cleaner
Find and manage large email attachments
"""
import logging
import base64
import os
from typing import List, Dict, Optional
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from auth import get_credentials
from config import GMAIL_MIN_ATTACHMENT_SIZE_MB, GMAIL_MAX_RESULTS, GMAIL_DUMP_DIR
from tqdm import tqdm

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


class GmailAttachmentScanner:
    """Scan and manage Gmail attachments."""
    
    def __init__(self, min_size_mb: int = GMAIL_MIN_ATTACHMENT_SIZE_MB):
        """
        Initialize scanner.
        
        Args:
            min_size_mb: Minimum attachment size to scan for (in MB)
        """
        self.service = build('gmail', 'v1', credentials=get_credentials())
        self.min_size_bytes = min_size_mb * 1024 * 1024
        self.min_size_mb = min_size_mb
    
    def search_emails_with_large_attachments(self, max_results: int = GMAIL_MAX_RESULTS) -> List[Dict]:
        """
        Search for emails with large attachments.
        
        Args:
            max_results: Maximum number of emails to scan
        
        Returns:
            List of email metadata with attachment info
        """
        print(f"📧 Scanning Gmail for emails with attachments > {self.min_size_mb}MB...")
        
        # Gmail search query for emails with attachments
        query = f"has:attachment larger:{self.min_size_mb}M"
        
        emails_with_attachments = []
        page_token = None
        
        try:
            while True:
                results = self.service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=min(500, max_results),
                    pageToken=page_token
                ).execute()
                
                messages = results.get('messages', [])
                
                if not messages:
                    break
                
                print(f"   Found {len(emails_with_attachments) + len(messages)} emails...", end='\r')
                
                # Get full message details with progress bar
                pbar = tqdm(messages, desc="Loading details", ncols=80, 
                           bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}', leave=False)
                
                for message in pbar:
                    msg_id = message['id']
                    msg_data = self.get_message_details(msg_id)
                    
                    if msg_data and msg_data.get('attachments'):
                        emails_with_attachments.append(msg_data)
                
                pbar.close()
                
                page_token = results.get('nextPageToken')
                
                if not page_token or len(emails_with_attachments) >= max_results:
                    break
        
        except HttpError as e:
            logger.error(f"HTTP Error searching emails: {e}")
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
        
        print(f"\n✅ Found {len(emails_with_attachments)} emails with large attachments")
        return emails_with_attachments
    
    def get_message_details(self, msg_id: str) -> Optional[Dict]:
        """
        Get detailed message information including attachments.
        
        Args:
            msg_id: Gmail message ID
        
        Returns:
            Dictionary with message details and attachments
        """
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=msg_id,
                format='full'
            ).execute()
            
            # Extract headers
            headers = message.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')
            date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'Unknown')
            
            # Extract attachments
            attachments = []
            self._extract_attachments(message.get('payload', {}), attachments, msg_id)
            
            # Filter by size
            large_attachments = [
                att for att in attachments 
                if att['size'] >= self.min_size_bytes
            ]
            
            if not large_attachments:
                return None
            
            total_size = sum(att['size'] for att in large_attachments)
            
            return {
                'id': msg_id,
                'subject': subject,
                'from': sender,
                'date': date,
                'attachments': large_attachments,
                'total_attachment_size_bytes': total_size,
                'total_attachment_size_mb': total_size / (1024 * 1024),
                'num_attachments': len(large_attachments)
            }
        
        except Exception as e:
            logger.error(f"Error getting message {msg_id}: {e}")
            return None
    
    def _extract_attachments(self, payload: Dict, attachments: List[Dict], msg_id: str):
        """
        Recursively extract attachments from message payload.
        
        Args:
            payload: Message payload
            attachments: List to append attachments to
            msg_id: Message ID
        """
        if 'parts' in payload:
            for part in payload['parts']:
                self._extract_attachments(part, attachments, msg_id)
        
        if payload.get('filename'):
            attachment_id = payload.get('body', {}).get('attachmentId')
            size = payload.get('body', {}).get('size', 0)
            mime_type = payload.get('mimeType', 'unknown')
            
            if attachment_id and size > 0:
                attachments.append({
                    'id': attachment_id,
                    'filename': payload['filename'],
                    'mime_type': mime_type,
                    'size': size,
                    'size_mb': size / (1024 * 1024),
                    'message_id': msg_id
                })
    
    def calculate_stats(self, emails: List[Dict]) -> Dict:
        """
        Calculate statistics about email attachments.
        
        Args:
            emails: List of email metadata
        
        Returns:
            Statistics dictionary
        """
        total_size = sum(email['total_attachment_size_bytes'] for email in emails)
        total_attachments = sum(email['num_attachments'] for email in emails)
        
        # Group by file type
        by_type = {}
        for email in emails:
            for att in email['attachments']:
                mime_type = att['mime_type']
                if mime_type not in by_type:
                    by_type[mime_type] = {
                        'count': 0,
                        'size_bytes': 0,
                        'size_mb': 0
                    }
                by_type[mime_type]['count'] += 1
                by_type[mime_type]['size_bytes'] += att['size']
                by_type[mime_type]['size_mb'] += att['size_mb']
        
        # Sort emails by size
        emails_sorted = sorted(emails, key=lambda x: x['total_attachment_size_bytes'], reverse=True)
        
        return {
            'total_emails': len(emails),
            'total_attachments': total_attachments,
            'total_size_bytes': total_size,
            'total_size_mb': total_size / (1024 * 1024),
            'total_size_gb': total_size / (1024 * 1024 * 1024),
            'by_type': by_type,
            'emails_sorted': emails_sorted
        }
    
    def download_attachment(self, msg_id: str, attachment_id: str, filename: str, destination: Path) -> bool:
        """
        Download an attachment from Gmail.
        
        Args:
            msg_id: Message ID
            attachment_id: Attachment ID
            filename: Attachment filename
            destination: Local path to save to
        
        Returns:
            True if successful
        """
        try:
            attachment = self.service.users().messages().attachments().get(
                userId='me',
                messageId=msg_id,
                id=attachment_id
            ).execute()
            
            file_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
            
            with open(destination, 'wb') as f:
                f.write(file_data)
            
            return True
        
        except Exception as e:
            logger.error(f"Error downloading attachment {filename}: {e}")
            return False
    
    def delete_email(self, msg_id: str) -> bool:
        """
        Delete an email (moves to trash).
        
        Args:
            msg_id: Message ID
        
        Returns:
            True if successful
        """
        try:
            self.service.users().messages().trash(
                userId='me',
                id=msg_id
            ).execute()
            return True
        
        except Exception as e:
            logger.error(f"Error deleting email {msg_id}: {e}")
            return False
    
    def dump_and_delete_emails(self, email: Dict) -> Dict:
        """
        Download attachments locally, then DELETE email from Gmail.
        
        Args:
            email: Email metadata with attachments
        
        Returns:
            Results of dump+delete operation
        """
        msg_id = email['id']
        subject = email['subject'][:50]
        
        # Create folder for this email
        safe_subject = "".join(c for c in subject if c.isalnum() or c in (' ', '-', '_')).strip()
        email_folder = GMAIL_DUMP_DIR / f"{msg_id}_{safe_subject}"
        email_folder.mkdir(exist_ok=True)
        
        downloaded = []
        failed = []
        
        for att in email['attachments']:
            local_path = email_folder / att['filename']
            
            if self.download_attachment(msg_id, att['id'], att['filename'], local_path):
                downloaded.append({
                    'filename': att['filename'],
                    'size': att['size'],
                    'local_path': str(local_path)
                })
            else:
                failed.append(att['filename'])
        
        # Delete email after downloading attachments
        deleted = self.delete_email(msg_id)
        
        # Create README
        readme_path = email_folder / 'README.txt'
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(f"Email: {email['subject']}\n")
            f.write(f"From: {email['from']}\n")
            f.write(f"Date: {email['date']}\n")
            f.write(f"Total Size: {email['total_attachment_size_mb']:.2f} MB\n")
            f.write(f"Attachments: {len(email['attachments'])}\n")
            f.write(f"Downloaded: {len(downloaded)}\n")
            f.write(f"Failed: {len(failed)}\n")
            f.write(f"Email Deleted: {'Yes' if deleted else 'No'}\n\n")
            f.write("=" * 70 + "\n")
            f.write("Attachments:\n")
            f.write("=" * 70 + "\n\n")
            for att in email['attachments']:
                status = "✅ Downloaded" if att['filename'] in [d['filename'] for d in downloaded] else "❌ Failed"
                f.write(f"- {att['filename']} ({att['size_mb']:.2f} MB) - {status}\n")
        
        return {
            'downloaded': downloaded,
            'failed': failed,
            'deleted': deleted,
            'dump_folder': str(email_folder),
            'space_freed_mb': email['total_attachment_size_mb'] if deleted else 0
        }
    
    def generate_report(self, stats: Dict, top_n: int = 20) -> str:
        """Generate human-readable report."""
        report = []
        report.append("=" * 70)
        report.append("📧 GMAIL ATTACHMENT REPORT")
        report.append("=" * 70)
        report.append("")
        report.append("📈 SUMMARY")
        report.append(f"   Total emails with attachments: {stats['total_emails']:,}")
        report.append(f"   Total attachments: {stats['total_attachments']:,}")
        report.append(f"   Total size: {stats['total_size_gb']:.2f} GB ({stats['total_size_mb']:.1f} MB)")
        report.append("")
        
        # By type
        report.append("📁 BY FILE TYPE")
        report.append("-" * 70)
        for mime_type, data in sorted(stats['by_type'].items(), key=lambda x: x[1]['size_bytes'], reverse=True):
            report.append(f"{mime_type}")
            report.append(f"   Count: {data['count']:,} files")
            report.append(f"   Size: {data['size_mb']:.2f} MB")
            report.append("")
        
        # Top emails
        report.append(f"🔝 TOP {top_n} LARGEST EMAILS")
        report.append("-" * 70)
        for i, email in enumerate(stats['emails_sorted'][:top_n], 1):
            report.append(f"{i}. {email['subject'][:60]}")
            report.append(f"   From: {email['from']}")
            report.append(f"   Date: {email['date']}")
            report.append(f"   Attachments: {email['num_attachments']} files ({email['total_attachment_size_mb']:.2f} MB)")
            for att in email['attachments']:
                report.append(f"     - {att['filename']} ({att['size_mb']:.2f} MB)")
            report.append("")
        
        report.append("=" * 70)
        return "\n".join(report)
