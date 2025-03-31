import pyfiglet
T = input("Enter Text you want to convert to ASCII art : ")
ASCII_art_1 = pyfiglet.figlet_format(T,font='isometric1')
print(ASCII_art_1)


# from PIL import Image # type: ignore

# # ASCII characters used to build the output text
# ASCII_CHARS = ['@', '%', '#', '*', '+', '=', '-', ':', '.', ' ']

# def resize_image(image, new_width=100):
#     width, height = image.size
#     ratio = height / width / 1.65  # Adjusting for character height
#     new_height = int(new_width * ratio)
#     return image.resize((new_width, new_height))

# def grayify(image):
#     return image.convert("L")  # Convert to grayscale

# def pixels_to_ascii(image):
#     pixels = image.getdata()
#     ascii_str = ''.join([ASCII_CHARS[pixel // 25] for pixel in pixels])
#     return ascii_str

# def image_to_ascii(image_path, new_width=100):
#     try:
#         image = Image.open(image_path)
#     except Exception as e:
#         return str(e)

#     image = resize_image(image, new_width)
#     grayscale_image = grayify(image)
    
#     ascii_str = pixels_to_ascii(grayscale_image)
#     img_width = grayscale_image.width

#     ascii_img = "\n".join([ascii_str[i:i+img_width] for i in range(0, len(ascii_str), img_width)])
#     return ascii_img

# # Example usage
# ascii_art = image_to_ascii("penguin.png", new_width=80)
# print(ascii_art)
