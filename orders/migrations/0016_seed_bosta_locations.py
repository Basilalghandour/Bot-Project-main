# in orders/migrations/000X_seed_bosta_locations.py

from django.db import migrations

# This is the list of cities (governorates) from the data you provided
CITIES_DATA = [
    {"_id": "Jrb6X6ucjiYgMP4T7", "name": "Alexandria", "code": "EG-02"},
    {"_id": "7mDPAohM3ArSZmWTm", "name": "Assuit", "code": "EG-17"},
    {"_id": "kLvZ5JY6LJPL5chzN", "name": "Aswan", "code": "EG-21"},
    {"_id": "LzbbvTzZ7D2CgE2PL", "name": "Bani Suif", "code": "EG-16"},
    {"_id": "g3GchTSmCgR2JynsJ", "name": "Behira", "code": "EG-04"},
    {"_id": "FceDyHXwpSYYF9zGW", "name": "Cairo", "code": "EG-01"},
    {"_id": "RrDhS8YYsXAwZ9Zfo", "name": "Dakahlia", "code": "EG-05"},
    {"_id": "qoZvYcZ8Cqji4pGp5", "name": "Damietta", "code": "EG-14"},
    {"_id": "yp3atroeTwnyiBNKE", "name": "El Kalioubia", "code": "EG-06"},
    {"_id": "BW5MiNxEirB7tuz2y", "name": "Fayoum", "code": "EG-15"},
    {"_id": "K3RwC677J8kJytdZD", "name": "Gharbia", "code": "EG-07"},
    {"_id": "0064Qb0OgcA", "name": "Giza", "code": "EG-25"},
    {"_id": "PJqNriLtFtx2cfkKP", "name": "Ismailia", "code": "EG-11"},
    {"_id": "ByP7rFCjL6XzF6j4S", "name": "Kafr Alsheikh", "code": "EG-08"},
    {"_id": "wgYEdH2WMzxGE2Ztp", "name": "Luxor", "code": "EG-22"},
    {"_id": "KBpGiRZJMIx", "name": "Matrouh", "code": "EG-28"},
    {"_id": "si6eLnKjXqTFTMBj9", "name": "Menya", "code": "EG-19"},
    {"_id": "ruBSjGBDX9wpRa3cc", "name": "Monufia", "code": "EG-09"},
    {"_id": "w4yDVHVJWqa4HpbzA", "name": "New Valley", "code": "EG-24"},
    {"_id": "2hGtNLfRgqGrJjnW9", "name": "North Coast", "code": "EG-03"},
    {"_id": "ZuCaDAVQlPT", "name": "North Sinai", "code": "EG-27"},
    {"_id": "skFtf6ZmKo8kBEBDK", "name": "Port Said", "code": "EG-13"},
    {"_id": "vfTHTes3uGjAszgtg", "name": "Qena", "code": "EG-20"},
    {"_id": "r5TscLCNSjR2GimxQ", "name": "Red Sea", "code": "EG-23"},
    {"_id": "6ExcoGbpYHnggP8JD", "name": "Sharqia", "code": "EG-10"},
    {"_id": "n3EENg2adhuR9xBZK", "name": "Sohag", "code": "EG-18"},
    {"_id": "nG_c44vHQht", "name": "South Sinai", "code": "EG-26"},
    {"_id": "PickurJ5uJZ9rDTHW", "name": "Suez", "code": "EG-12"},
]

def populate_cities(apps, schema_editor):
    """
    Populates the BostaCity table with the initial data from Bosta's API.
    """
    BostaCity = apps.get_model('orders', 'BostaCity')
    for city_data in CITIES_DATA:
        BostaCity.objects.update_or_create(
            bosta_id=city_data['_id'],
            defaults={
                'name': city_data['name'],
                'country_code': city_data.get('code', 'EG') # Using 'country_code' to store the governorate code
            }
        )

def revert_cities(apps, schema_editor):
    """
    Deletes the data if the migration is rolled back.
    """
    BostaCity = apps.get_model('orders', 'BostaCity')
    BostaCity.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0015_bostacity_bostadistrict'), # Replace with the name of your previous migration file
    ]

    operations = [
        migrations.RunPython(populate_cities, reverse_code=revert_cities),
    ]