import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageCms
from io import BytesIO
import os
from scipy.signal import convolve2d

def load_image(image_path):
    return Image.open(image_path).convert('L')  # Convert to grayscale

def check_resolution(image):
    width, height = image.size
    return f"Image resolution: {width}x{height} pixels"

def check_color_depth(image):
    mode = image.mode
    if mode == 'RGB':
        return "Color depth: 24-bit (8 bits per channel), adequate for high-quality printing."
    elif mode == 'RGBA':
        return "Color depth: 32-bit (8 bits per channel with alpha), adequate for high-quality printing."
    elif mode == 'L':
        return "Color depth: 8-bit grayscale, may be adequate depending on print requirements."
    elif mode == 'CMYK':
        return "Color depth: 32-bit CMYK, suitable for professional printing."
    else:
        return f"Color depth: {mode}, may not be optimal for high-quality printing."

def simulate_halftone_screening(image, print_dpi):
    halftone_image = image.filter(ImageFilter.CONTOUR)  # Basic example of a simulation
    return halftone_image, "Halftone screening simulation complete."

def check_file_size(image_path):
    import os
    size_bytes = os.path.getsize(image_path)
    size_mb = size_bytes / (1024 * 1024)
    return f"File size: {size_mb:.2f} MB"

def check_bleed_and_margins(image, desired_width_inch, desired_height_inch, bleed_inch, dpi):
    required_width_px = int((desired_width_inch + 2 * bleed_inch) * dpi)
    required_height_px = int((desired_height_inch + 2 * bleed_inch) * dpi)

    if image.width >= required_width_px and image.height >= required_height_px:
        return "Image dimensions are sufficient for bleed."
    else:
        return f"Image is too small. Required: {required_width_px}x{required_height_px}px, Actual: {image.width}x{image.height}px"

def get_icc_profile(image):
    if 'icc_profile' in image.info:
        try:
            profile = ImageCms.ImageCmsProfile(BytesIO(image.info['icc_profile']))
            return profile.profile.profile_description
        except Exception as e:
            return f"ICC profile present but unreadable: {str(e)}"
    return "No ICC profile found"

def check_color_profile(image):
    profile_description = get_icc_profile(image)
    color_mode = image.mode
    return f"Color mode: {color_mode}, ICC Profile: {profile_description}"

def convert_color_profile(image, target_profile_path):
    if not os.path.exists(target_profile_path):
        return image, f"Color profile conversion failed: Profile file not found at {target_profile_path}"
    
    try:
        target_profile = ImageCms.ImageCmsProfile(target_profile_path)
        
        # Get the input profile from the image, or use a default sRGB profile
        if 'icc_profile' in image.info:
            input_profile = ImageCms.ImageCmsProfile(BytesIO(image.info['icc_profile']))
        else:
            input_profile = ImageCms.createProfile('sRGB')
        
        # Convert to the desired color profile
        converted_image = ImageCms.profileToProfile(image, input_profile, target_profile)
        return converted_image, "Color profile conversion completed successfully."
    except Exception as e:
        return image, f"Color profile conversion failed: {str(e)}"

def check_sharpness(image):
    # Convert PIL Image to OpenCV format
    cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    
    # Use the variance of the Laplacian as a sharpness metric
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = laplacian.var()
    
    threshold = 100  # This threshold should be adjusted based on testing
    if sharpness < threshold:
        return f"Image appears blurry (sharpness: {sharpness:.2f}). Consider sharpening or using a different image."
    else:
        return f"Image sharpness is adequate for printing (sharpness: {sharpness:.2f})."

def check_aspect_ratio(image, desired_width_inch, desired_height_inch):
    image_aspect_ratio = image.width / image.height
    desired_aspect_ratio = desired_width_inch / desired_height_inch

    if abs(image_aspect_ratio - desired_aspect_ratio) < 0.01:  # Allow for small rounding differences
        return f"Aspect ratio matches the print dimensions. Image: {image_aspect_ratio:.2f}, Desired: {desired_aspect_ratio:.2f}"
    else:
        return f"Aspect ratio mismatch. Image: {image_aspect_ratio:.2f}, Desired: {desired_aspect_ratio:.2f}. Cropping or distortion may occur."

def detect_compression_artifacts(image, block_size=8, detail_threshold=0.1, edge_threshold=20):
    # Convert PIL Image to numpy array
    img_array = np.array(image)
    
    # Convert to grayscale if it's a color image
    if len(img_array.shape) == 3:
        img_gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        img_gray = img_array

    # 1. Detect blockiness
    def detect_blockiness(img, block_size):
        h, w = img.shape
        
        # Create kernels for horizontal and vertical edge detection
        kernel_h = np.zeros((block_size, block_size))
        kernel_h[:, -1] = 1
        kernel_h[:, 0] = -1
        
        kernel_v = np.zeros((block_size, block_size))
        kernel_v[-1, :] = 1
        kernel_v[0, :] = -1
        
        # Convolve the image with the kernels
        block_diff_h = convolve2d(img, kernel_h, mode='valid', boundary='symm')
        block_diff_v = convolve2d(img, kernel_v, mode='valid', boundary='symm')
        
        # Calculate the mean of the absolute differences
        return (np.mean(np.abs(block_diff_h)) + np.mean(np.abs(block_diff_v))) / 2

    blockiness = detect_blockiness(img_gray, block_size)

    # 2. Detect loss of detail
    def detect_detail_loss(img, threshold):
        laplacian = cv2.Laplacian(img, cv2.CV_64F)
        return np.mean(np.abs(laplacian) < threshold)

    detail_loss = detect_detail_loss(img_gray, detail_threshold)

    # 3. Detect ringing artifacts (often visible near edges)
    def detect_ringing(img, threshold):
        sobel_x = cv2.Sobel(img, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(img, cv2.CV_64F, 0, 1, ksize=3)
        magnitude = np.sqrt(sobel_x**2 + sobel_y**2)
        kernel = np.array([[-1, -1, -1], [-1, 8, -1], [-1, -1, -1]])
        filtered = convolve2d(magnitude, kernel, mode='same', boundary='symm')
        return np.mean(filtered > threshold)

    ringing = detect_ringing(img_gray, edge_threshold)

    # Combine metrics and determine overall artifact level
    artifact_level = (blockiness + detail_loss + ringing) / 3

    if artifact_level > 0.1:  # This threshold can be adjusted based on testing
        return f"Significant compression artifacts detected (level: {artifact_level:.2f}). " \
               f"Blockiness: {blockiness:.2f}, Detail loss: {detail_loss:.2f}, Ringing: {ringing:.2f}. " \
               f"This may affect print quality on physical media."
    else:
        return f"No significant compression artifacts detected (level: {artifact_level:.2f}). " \
               f"Blockiness: {blockiness:.2f}, Detail loss: {detail_loss:.2f}, Ringing: {ringing:.2f}. " \
               f"The image should print well on physical media."

def check_exposure(image):
    # Convert PIL Image to OpenCV format
    cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    grayscale = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    
    # Calculate histogram
    hist = cv2.calcHist([grayscale], [0], None, [256], [0, 256])
    
    # Analyze histogram for exposure issues
    dark_threshold = 5  # Percentage of pixels that can be very dark
    bright_threshold = 5  # Percentage of pixels that can be very bright
    total_pixels = grayscale.shape[0] * grayscale.shape[1]
    
    dark_pixels = np.sum(hist[:10]) / total_pixels * 100
    bright_pixels = np.sum(hist[-10:]) / total_pixels * 100
    
    if dark_pixels > dark_threshold:
        return f"Image may be underexposed. {dark_pixels:.2f}% of pixels are very dark (threshold: {dark_threshold}%)."
    elif bright_pixels > bright_threshold:
        return f"Image may be overexposed. {bright_pixels:.2f}% of pixels are very bright (threshold: {bright_threshold}%)."
    else:
        return f"Exposure is within acceptable limits. Dark pixels: {dark_pixels:.2f}%, Bright pixels: {bright_pixels:.2f}%."

def run_checks(image_path, print_dpi, desired_width_inch, desired_height_inch, bleed_inch):
    try:
        image = Image.open(image_path)
    except Exception as e:
        return {"error": f"Failed to open image: {str(e)}"}, None

    results = {
        "resolution": check_resolution(image),
        "color_depth": check_color_depth(image),
        "file_size": check_file_size(image_path),
        "bleed_and_margins": check_bleed_and_margins(image, desired_width_inch, desired_height_inch, bleed_inch, print_dpi),
        "color_profile": check_color_profile(image),
        "sharpness": check_sharpness(image),
        "aspect_ratio": check_aspect_ratio(image, desired_width_inch, desired_height_inch),
        "compression_artifacts": detect_compression_artifacts(image),
        "exposure": check_exposure(image),
    }
    
    # Convert to grayscale for halftone simulation
    grayscale_image = image.convert('L')
    halftone_image, halftone_message = simulate_halftone_screening(grayscale_image, print_dpi)
    results["halftone"] = halftone_message
    
    return results, halftone_image

def print_image_info(image_path):
    try:
        with Image.open(image_path) as img:
            print(f"Image: {image_path}")
            print(f"Format: {img.format}")
            print(f"Mode: {img.mode}")
            print(f"Size: {img.size}")
            print(f"Width: {img.width}")
            print(f"Height: {img.height}")
            print(f"Palette: {img.palette}")
            print(f"Info: {img.info}")
            
            if 'dpi' in img.info:
                print(f"DPI: {img.info['dpi']}")
            
            if 'exif' in img.info:
                print("EXIF data:")
                for key, value in img.getexif().items():
                    print(f"  {key}: {value}")
            
            if 'icc_profile' in img.info:
                try:
                    profile = ImageCms.ImageCmsProfile(BytesIO(img.info['icc_profile']))
                    print(f"ICC Profile: {profile.profile.profile_description}")
                except Exception as e:
                    print(f"ICC profile present but unreadable: {str(e)}")
            else:
                print("No ICC profile found")
            
            print(f"Bands: {img.getbands()}")
            print(f"Bit depth: {img.bits}")
            print(f"Layers: {getattr(img, 'layers', 'Not applicable')}")
            
            # File information
            file_size = os.path.getsize(image_path)
            print(f"File size: {file_size} bytes ({file_size/1024:.2f} KB)")
            
            print(f"Animated: {getattr(img, 'is_animated', False)}")
            print(f"Frames: {getattr(img, 'n_frames', 1)}")
            
    except Exception as e:
        print(f"Error opening image: {str(e)}")

if __name__ == "__main__":
    image_path = "/Users/ryan/Desktop/crazygpt/for_honored_bigdoggydog.png"
    print_dpi = 300
    desired_width_inch = 8.5
    desired_height_inch = 11
    bleed_inch = 0.125
    #target_profile_path = "path/to/target/profile.icc"  # Optional
    
    results, halftone_image = run_checks(image_path, print_dpi, desired_width_inch, desired_height_inch, bleed_inch) #target_profile_path)
    
    for check, result in results.items():
        print(f"{check.capitalize()}: {result}")
    
    if halftone_image:
        halftone_image.show()  # Preview the halftone simulation

    print_image_info(image_path)
