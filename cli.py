import argparse
import sys
from tqdm import tqdm
from drive_service import DriveCleanupService
from drive_duplicates import DriveDuplicateFinder
from drive_similar_images import SimilarImageFinder
from config import PROJECT_NAME, VERSION, SIMILARITY_THRESHOLD


def scan_drive(min_size_mb: int):
    """Scan Google Drive for large files."""
    print(f"\n🔍 Scanning Drive for files > {min_size_mb}MB...\n")
    
    service = DriveCleanupService()
    files = service.list_large_media_files(min_size_mb * 1024 * 1024)
    space_mb = service.calculate_space(files)
    
    print(f"✅ Found {len(files)} files")
    print(f"💾 Total space: {space_mb:.2f} MB ({space_mb/1024:.2f} GB)")


def find_duplicates(dump: bool = False):
    """Find duplicate files in Drive."""
    print("\n🔍 Scanning Drive for duplicate files...\n")
    
    finder = DriveDuplicateFinder()
    
    # Scan Drive
    files = finder.list_all_files()
    
    if not files:
        print("❌ No files found in Drive")
        return
    
    # Find duplicates
    duplicates = finder.find_duplicates(files)
    
    if not duplicates:
        print("\n✅ No duplicates found! Your Drive is clean.")
        return
    
    # Calculate stats
    stats = finder.calculate_wasted_space(duplicates)
    
    # Show summary
    print(f"\n📊 RESULTS:")
    print(f"   Duplicate files: {stats['total_duplicate_files']:,}")
    print(f"   Duplicate groups: {stats['total_duplicate_groups']:,}")
    print(f"   Wasted space: {stats['total_wasted_gb']:.2f} GB\n")
    
    # Show top 10
    print("🔝 TOP 10 SPACE WASTERS:")
    for i, group in enumerate(stats['duplicate_groups'][:10], 1):
        print(f"{i}. {group['filename']}")
        print(f"   {group['num_copies']} copies × {group['file_size_mb']:.1f} MB = {group['wasted_mb']:.1f} MB wasted")
    
    # Generate full report
    report = finder.generate_report(stats)
    report_file = 'duplicate_report.txt'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n💾 Full report saved to: {report_file}")
    
    # Optional: Dump duplicates to local folder AND DELETE FROM DRIVE
    if dump:
        print("\n" + "=" * 70)
        print("⚠️  DUMP & DELETE MODE")
        print("=" * 70)
        print("\n🚨 WARNING: This will:")
        print("   1. Download duplicate files to local 'duplicates_dump' folder")
        print("   2. DELETE duplicate files from Google Drive (keeps oldest copy)")
        print("   3. Skip shared files (no permission to delete)")
        print("   4. Free up space immediately\n")
        print("💡 The oldest copy of each file will be KEPT in Drive.")
        print("💡 All other copies will be DOWNLOADED then DELETED.\n")
        
        confirm = input("⚠️  Are you SURE you want to proceed? Type 'YES' to confirm: ")
        
        if confirm == 'YES':
            print("\n📥 Processing duplicates...\n")
            
            total_freed_mb = 0
            total_deleted = 0
            total_skipped = 0
            total_failed = 0
            
            # Single progress bar for all groups
            pbar = tqdm(stats['duplicate_groups'], 
                       desc="Dumping & deleting", 
                       ncols=80,
                       bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]')
            
            for group in pbar:
                result = finder.dump_and_delete_duplicates(group, keep_index=0)
                total_freed_mb += result['space_freed_mb']
                total_deleted += len(result['deleted_from_drive'])
                total_skipped += len(result['skipped_no_permission'])
                total_failed += len(result['failed'])
            
            pbar.close()
            
            print("\n" + "=" * 70)
            print("✅ DUMP & DELETE COMPLETE")
            print("=" * 70)
            print(f"\n📊 RESULTS:")
            print(f"   Groups processed: {len(stats['duplicate_groups'])}")
            print(f"   Files deleted from Drive: {total_deleted}")
            print(f"   Files kept in Drive: {len(stats['duplicate_groups'])}")
            print(f"   Files skipped (no permission): {total_skipped}")
            print(f"   Files failed: {total_failed}")
            print(f"   Space freed: {total_freed_mb:.2f} MB ({total_freed_mb/1024:.2f} GB)")
            print(f"   📂 Local backup: duplicates_dump/")
            
            if total_skipped > 0:
                print(f"\n⚠️  NOTE: {total_skipped} files were skipped (shared files you don't own)")
                print("   These files were downloaded but NOT deleted from Drive")
            
            print(f"\n💡 Next steps:")
            print(f"   1. Review dumped files in 'duplicates_dump/' folder")
            print(f"   2. Check README.txt in each subfolder for details")
            print(f"   3. Delete local copies if you don't need them")
            print(f"   4. Check your Drive storage - it should be lower now!")
            print("=" * 70)
        else:
            print("❌ Cancelled - No files were deleted")


def find_similar_images(threshold: float, dump: bool = False):
    """Find visually similar images in Drive."""
    print(f"\n📸 Scanning Drive for similar images (threshold: {threshold*100:.0f}%)...\n")
    
    finder = SimilarImageFinder(similarity_threshold=threshold)
    
    images = finder.list_all_images()
    
    if not images:
        print("❌ No images found in Drive")
        return
    
    # NO LIMIT - Process all images
    print(f"🔍 Processing all {len(images)} images (this may take a while)...\n")
    
    hashes = finder.compute_hashes_for_images(images)
    
    if not hashes:
        print("❌ Failed to compute hashes")
        return
    
    similar_groups = finder.find_similar_images(images, hashes)
    
    if not similar_groups:
        print("\n✅ No similar images found!")
        return
    
    stats = finder.calculate_wasted_space(similar_groups)
    
    print(f"\n📊 RESULTS:")
    print(f"   Similar images: {stats['total_similar_files']:,}")
    print(f"   Similar groups: {stats['total_groups']:,}")
    print(f"   Wasted space: {stats['total_wasted_gb']:.2f} GB\n")
    
    print("🔝 TOP 5 SIMILAR IMAGE GROUPS:")
    for i, group in enumerate(stats['similar_groups'][:5], 1):
        keeper = group['keeper']
        print(f"{i}. {keeper['name']} (KEEPER)")
        print(f"   {group['num_similar'] - 1} similar images")
        print(f"   Wasted: {group['wasted_mb']:.2f} MB")
    
    report = finder.generate_report(stats)
    report_file = 'similar_images_report.txt'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n💾 Full report saved to: {report_file}")
    
    # Optional: Dump similar images AND DELETE FROM DRIVE
    if dump:
        print("\n" + "=" * 70)
        print("⚠️  DUMP & DELETE MODE - SIMILAR IMAGES")
        print("=" * 70)
        print("\n🚨 WARNING: This will:")
        print("   1. Download similar images to local 'duplicates_dump' folder")
        print("   2. DELETE similar images from Google Drive (keeps largest/best quality)")
        print("   3. Skip shared files (no permission to delete)")
        print("   4. Free up space immediately\n")
        print("💡 The LARGEST (best quality) image in each group will be KEPT in Drive.")
        print("💡 All other similar images will be DOWNLOADED then DELETED.\n")
        
        confirm = input("⚠️  Are you SURE you want to proceed? Type 'YES' to confirm: ")
        
        if confirm == 'YES':
            print("\n📥 Processing similar images...\n")
            
            total_freed_mb = 0
            total_deleted = 0
            total_skipped = 0
            total_failed = 0
            
            pbar = tqdm(stats['similar_groups'], 
                       desc="Dumping & deleting similar", 
                       ncols=80,
                       bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]')
            
            for group in pbar:
                result = finder.dump_and_delete_similar(group, keep_index=0)
                total_freed_mb += result['space_freed_mb']
                total_deleted += len(result['deleted_from_drive'])
                total_skipped += len(result['skipped_no_permission'])
                total_failed += len(result['failed'])
            
            pbar.close()
            
            print("\n" + "=" * 70)
            print("✅ DUMP & DELETE COMPLETE - SIMILAR IMAGES")
            print("=" * 70)
            print(f"\n📊 RESULTS:")
            print(f"   Groups processed: {len(stats['similar_groups'])}")
            print(f"   Files deleted from Drive: {total_deleted}")
            print(f"   Files kept in Drive: {len(stats['similar_groups'])}")
            print(f"   Files skipped (no permission): {total_skipped}")
            print(f"   Files failed: {total_failed}")
            print(f"   Space freed: {total_freed_mb:.2f} MB ({total_freed_mb/1024:.2f} GB)")
            print(f"   📂 Local backup: duplicates_dump/")
            
            if total_skipped > 0:
                print(f"\n⚠️  NOTE: {total_skipped} files were skipped (shared files you don't own)")
            
            print(f"\n💡 Next steps:")
            print(f"   1. Review dumped files in 'duplicates_dump/' folder")
            print(f"   2. Check README.txt in each subfolder for details")
            print(f"   3. Delete local copies if you don't need them")
            print("=" * 70)
        else:
            print("❌ Cancelled - No files were deleted")


def main():
    parser = argparse.ArgumentParser(
        description=f"{PROJECT_NAME} v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py drive-scan --min-size 10          # Find large files
  python cli.py drive-duplicates                  # Find exact duplicates (read-only)
  python cli.py drive-duplicates --dump           # Delete duplicates from Drive
  python cli.py drive-similar --threshold 0.90    # Find similar images (read-only)
  python cli.py drive-similar --threshold 0.90 --dump  # Delete similar images
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Drive scan
    drive_scan_parser = subparsers.add_parser('drive-scan', help='Scan Drive for large files')
    drive_scan_parser.add_argument('--min-size', type=int, default=5)
    
    # Drive duplicates
    drive_dup_parser = subparsers.add_parser('drive-duplicates', help='Find duplicate files')
    drive_dup_parser.add_argument('--dump', action='store_true')
    
    # Drive similar images
    drive_similar_parser = subparsers.add_parser('drive-similar', help='Find similar images')
    drive_similar_parser.add_argument('--threshold', type=float, default=SIMILARITY_THRESHOLD)
    drive_similar_parser.add_argument('--dump', action='store_true', 
                                     help='⚠️  Download + DELETE similar images (keeps best quality)')
    
    args = parser.parse_args()
    
    if args.command == 'drive-scan':
        scan_drive(args.min_size)
    elif args.command == 'drive-duplicates':
        find_duplicates(dump=args.dump)
    elif args.command == 'drive-similar':
        find_similar_images(args.threshold, dump=args.dump)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
