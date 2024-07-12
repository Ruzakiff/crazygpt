from vininfo import Vin

def get_vin_input():
    return input("Enter a VIN: ").upper()

def display_vin_info(vin):
    print("Basic Information:")
    print(f"Country: {vin.country}")
    print(f"Manufacturer: {vin.manufacturer}")
    print(f"Region: {vin.region}")
    print(f"Years: {', '.join(map(str, vin.years))}")
    
    print("\nDetailed Information:")
    if vin.details:
        for key, value in vin.details.__dict__.items():
            if value:
                print(f"{key.capitalize()}: {value}")
    else:
        print("No detailed information available for this VIN.")

def verify_checksum(vin):
    return vin.verify_checksum()

def main():
    vin_string = get_vin_input()
    try:
        vin = Vin(vin_string)
        display_vin_info(vin)
        
        if verify_checksum(vin):
            print("\nChecksum is valid.")
        else:
            print("\nWarning: Checksum is invalid.")
    except ValueError as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()