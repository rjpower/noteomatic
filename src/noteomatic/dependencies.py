from typing import List

def check_ffmpeg() -> List[str]:
    """Check if ffmpeg is available through python-ffmpeg"""
    errors = []
    try:
        import ffmpeg
        # Try to access ffmpeg.input which requires the binary
        ffmpeg.input
    except ImportError:
        errors.append("python-ffmpeg package not installed")
    except AttributeError:
        errors.append("ffmpeg binary not found - please install ffmpeg")
    except Exception as e:
        errors.append(f"Unexpected error checking ffmpeg: {e}")
    return errors

def check_dependencies() -> List[str]:
    """Check all required dependencies
    Returns list of error messages, empty if all dependencies satisfied
    """
    errors = []
    
    # Check ffmpeg
    errors.extend(check_ffmpeg())
        
    return errors
