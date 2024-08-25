import cv2
import numpy as np
from PIL import Image
import os

HAS_TORCH = False
try:
    import torch
    import torchvision
    from torchvision.models.segmentation import deeplabv3_resnet50
    HAS_TORCH = True
except ImportError:
    print("PyTorch not available. Using GrabCut method for background removal.")
except Exception as e:
    print(f"Error importing PyTorch: {e}")
    print("Falling back to GrabCut method for background removal.")

def analyze_and_process_image(image_path, output_path):
    # Open the image with PIL to preserve transparency
    img = Image.open(image_path)
    img_array = np.array(img)

    # Check if the image has an alpha channel
    has_alpha = img_array.shape[2] == 4 if len(img_array.shape) == 3 else False

    # Determine if background removal is needed
    needs_bg_removal = False
    if not has_alpha:
        # Check if the image has a complex subject
        edges = cv2.Canny(cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY), 100, 200)
        if np.sum(edges) > 50000:  # Threshold can be adjusted
            needs_bg_removal = True

    # Perform background removal if needed
    if needs_bg_removal:
        img_array = remove_background(img_array)

    # Crop transparent or white borders
    img_array = crop_borders(img_array)

    # Save the processed image
    Image.fromarray(img_array).save(output_path)

    return f"Processed image saved to {output_path}"

def remove_background(img_array):
    if HAS_TORCH:
        try:
            return remove_background_semantic(img_array)
        except Exception as e:
            print(f"Error in semantic segmentation: {e}")
            print("Falling back to GrabCut method.")
    return remove_background_grabcut(img_array)

def remove_background_semantic(img_array):
    # Load pre-trained DeepLabV3 model
    model = deeplabv3_resnet50(pretrained=True)
    model.eval()

    # Prepare input
    input_tensor = torchvision.transforms.functional.to_tensor(Image.fromarray(img_array))
    input_batch = input_tensor.unsqueeze(0)

    # Run inference
    with torch.no_grad():
        output = model(input_batch)['out'][0]
    output_predictions = output.argmax(0)

    # Create mask (assuming class 15 is 'person' in COCO dataset)
    mask = output_predictions == 15

    # Apply mask to original image
    img_rgba = cv2.cvtColor(img_array, cv2.COLOR_RGB2RGBA)
    img_rgba[:, :, 3] = mask.numpy() * 255

    return img_rgba

def remove_background_grabcut(img_array):
    # Convert to RGB if it's in RGBA format
    if img_array.shape[2] == 4:
        img_rgb = cv2.cvtColor(img_array, cv2.COLOR_RGBA2RGB)
    else:
        img_rgb = img_array

    # Create initial mask
    mask = np.zeros(img_rgb.shape[:2], np.uint8)
    rect = (10, 10, img_rgb.shape[1]-20, img_rgb.shape[0]-20)

    # GrabCut algorithm
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(img_rgb, mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)

    # Refine the mask using edge detection
    edges = cv2.Canny(img_rgb, 100, 200)
    mask[edges != 0] = cv2.GC_PR_FGD

    # Run GrabCut again with the refined mask
    cv2.grabCut(img_rgb, mask, None, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_MASK)

    # Create final mask
    mask2 = np.where((mask == 2) | (mask == 0), 0, 1).astype('uint8')

    # Apply the mask to the original image
    img_rgba = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2RGBA)
    img_rgba[:, :, 3] = mask2 * 255

    return img_rgba

def crop_borders(img_array):
    if img_array.shape[2] == 4:
        # Use alpha channel for transparency
        mask = img_array[:,:,3] > 0
    else:
        # Assume white is the background
        mask = np.any(img_array[:,:,:3] < 255, axis=2)

    # Find the bounding box of the non-transparent/non-white pixels
    coords = np.argwhere(mask)
    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)

    # Crop the image
    return img_array[y_min:y_max+1, x_min:x_max+1]

def main():
    input_path = "/Users/ryan/Desktop/crazygpt/B8201_PT7__91531-enhanced.png"
    output_folder = os.path.dirname(input_path)
    output_filename = "processed_" + os.path.basename(input_path)
    output_path = os.path.join(output_folder, output_filename)
    
    result = analyze_and_process_image(input_path, output_path)
    print(result)

if __name__ == "__main__":
    main()
