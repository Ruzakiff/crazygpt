import os
import imghdr
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

counter = 0

def process_folder(folder_path):
    global counter
    # Check if the folder exists
    if not os.path.isdir(folder_path):
        print(f"Error: The folder '{folder_path}' does not exist.")
        return

    # Iterate through all files in the folder
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        
        # Check if it's a file (not a subdirectory) and an image
        if os.path.isfile(file_path) and is_image(file_path):
            print(f"Processing image: {filename}")
            metadata, original_path = process_image_with_openai(file_path)
            if metadata:
                print(f"Generated metadata: {metadata}")
            if metadata and metadata.strip() == "DELETE":
                delete_image_and_converted(original_path)
                counter += 1

    # You can add logic here to save the metadata or process it further
        
            # Add your image processing logic here
            # For example:
            # process_image(file_path)

            
def process_image_with_openai(file_path):
    from openai import OpenAI
    import base64
    
    # Ensure you have set your API key in the environment variables
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Convert .heic to .jpg if necessary
    original_path = file_path
    if file_path.lower().endswith('.heic'):
        file_path = convert_heic_to_jpg(file_path)
    
    # Read the image file
    with open(file_path, "rb") as image_file:
        image_data = image_file.read()
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "From the perspective of a crazy controlling gf,output whether I should make my bf delete the image on his phone--none of the girls in the image are of me. output only either DELETE OR KEEP"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64.b64encode(image_data).decode('utf-8')}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=256,
            temperature=0,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        
        # Process the response
        metadata = response.choices[0].message.content
        return metadata, original_path
        
    except Exception as e:
        print(f"Error processing {os.path.basename(file_path)}: {str(e)}")
        return None, file_path


def is_image(file_path):
    # Add support for .heic files
    if file_path.lower().endswith('.heic'):
        return True
    return imghdr.what(file_path) is not None

def convert_heic_to_jpg(file_path):
    print("converterd")
    with Image.open(file_path) as img:
        jpg_path = os.path.splitext(file_path)[0] + '.jpg'
        img.save(jpg_path, 'JPEG')
    return jpg_path

def delete_image_and_converted(file_path):
    base_path = os.path.splitext(file_path)[0]
    extensions = ['.heic', '.jpg', '.jpeg', '.png']
    
    for ext in extensions:
        path_to_delete = base_path + ext
        if os.path.exists(path_to_delete):
            try:
                os.remove(path_to_delete)
                print(f"Deleted image: {os.path.basename(path_to_delete)}")
            except Exception as e:
                print(f"Error deleting {os.path.basename(path_to_delete)}: {str(e)}")

def main():
    folder_path = input("Enter the folder path: ")
    process_folder(folder_path)

if __name__ == "__main__":
    main()
    print(counter)
