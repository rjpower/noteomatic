import shutil
import subprocess
from typing import List, Tuple

def check_ffmpeg() -> Tuple[bool, str]:
    """Check if ffmpeg is available and get version"""
    if not shutil.which('ffmpeg'):
        return False, "ffmpeg not found in PATH"
    
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              text=True, 
                              check=True)
        return True, result.stdout.split('\n')[0]
    except subprocess.CalledProcessError as e:
        return False, f"Error running ffmpeg: {e}"
    except Exception as e:
        return False, f"Unexpected error checking ffmpeg: {e}"

def check_dependencies() -> List[str]:
    """Check all required dependencies
    Returns list of error messages, empty if all dependencies satisfied
    """
    errors = []
    
    # Check ffmpeg
    ffmpeg_ok, ffmpeg_msg = check_ffmpeg()
    if not ffmpeg_ok:
        errors.append(f"FFmpeg dependency error: {ffmpeg_msg}")
        
    return errors
