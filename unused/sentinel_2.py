import csv
import json
import os

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from PIL import Image
from geojson_converter import get_coordinates_from_points
from pystac.extensions.eo import EOExtension as eo
from rasterio import features, warp, windows

# Define the bands to retrieve
bands = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12",]

def get_data(catalog, coordinates, time_of_interest, index):
    name = f"{index:04d}"
    area_of_interest = {"type": "Polygon", "coordinates": coordinates}
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        intersects=area_of_interest,
        datetime=time_of_interest,
        query={"eo:cloud_cover": {"lt": 10}},
    )

    items = search.item_collection()
    least_cloudy_item = min(items, key=lambda item: eo.ext(item).cloud_cover)

    asset_href = least_cloudy_item.assets["visual"].href

    with rasterio.open(asset_href) as ds:
        aoi_bounds = features.bounds(area_of_interest)
        warped_aoi_bounds = warp.transform_bounds(
            "epsg:4326", ds.crs, *aoi_bounds
        )
        aoi_window = windows.from_bounds(transform=ds.transform, *warped_aoi_bounds)
        img_data = ds.read(window=aoi_window)

    if is_valid(img_data):
        band_data = []
        for band in bands:
            asset_href = least_cloudy_item.assets[band].href
            with rasterio.open(asset_href) as ds:
                aoi_bounds = features.bounds(area_of_interest)
                warped_aoi_bounds = warp.transform_bounds(
                    "epsg:4326", ds.crs, *aoi_bounds
                )
                aoi_window = windows.from_bounds(transform=ds.transform, *warped_aoi_bounds)
                band_data.append(ds.read(window=aoi_window))

        np.savez(
            f"sentinel_2/{name}.npz",
            **{band: data for band, data in zip(bands, band_data)}
        )

        coordinates = get_coordinates_from_points()
        create_stats()
        with open("sentinel_2/stats.csv", "a", newline="") as stats:
            writer = csv.writer(stats)
            row = [name] + [np.shape(band) for band in band_data] + [coordinates[index]]
            writer.writerow(row)

        img = Image.fromarray(np.transpose(img_data, axes=[1, 2, 0]))
        img.save(f'sentinel_2/{name}.png')

def get_coordinates():
    with open("coordinates/squares.geojson", "r") as f:
        file = json.load(f)

    coordinates = []

    for feature in file["features"]:
        coordinates.append(feature["geometry"]["coordinates"])

    return coordinates

def create_stats():
    if os.path.exists('sentinel_2/stats.csv'):
        os.remove('sentinel_2/stats.csv')
        
    with open('sentinel_2/stats.csv', 'x') as file:
        file.write("name,B01,B02,B03,B04,B05,B06,B07,B08,B8A,B09,B11,B12,coordinates \n")

def is_valid(file):
    num_zeros = np.count_nonzero(file == 0)
    per_zeros = (num_zeros / file.size)
    return per_zeros < 0.01

def update_bounds(arr, low, high):
    shape = np.shape(arr)
    low = min(low, min(shape[1], shape[2]))
    high = max(high, max(shape[1], shape[2]))
    return low, high

def crop(arr, z):
    _, x, y = arr.shape
    start_x = (x - z) // 2
    start_y = (y - z) // 2
    end_x = start_x + z
    end_y = start_y + z
    new_arr = np.zeros((1, z, z))
    new_arr[0,:,:] = arr[0,start_x:end_x,start_y:end_y]

    print(np.shape(new_arr))
    
    return new_arr

def download_data():
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )

    time_of_interest = "2022-06-01/2022-08-01"
    coordinates = get_coordinates()

    for index, coordinate in enumerate(coordinates):
        get_data(catalog, coordinate, time_of_interest, index)

def crop_data():
    min_10, max_10 = 100000, 0
    min_20, max_20 = 100000, 0
    min_60, max_60 = 100000, 0
    
    for filename in os.listdir('sentinel_2'):
        if filename.endswith('.npz'):
            file = dict(np.load('sentinel_2/' + filename))

            for key in file.keys():
                if key in ['B01', 'B09']:
                    min_10, max_10 = update_bounds(file[key], min_10, max_10)
                elif key in ['B02', 'B03', 'B04', 'B08']:
                    min_20, max_20 = update_bounds(file[key], min_20, max_20)
                elif key in ['B05', 'B06', 'B07', 'B8A', 'B09', 'B11', 'B12']:
                    min_60, max_60 = update_bounds(file[key], min_60, max_60)
                else:
                    raise Exception("Invalid key")
    
            max_diff = max(max_10 - min_10, max_20 - min_20, max_60 - min_60)

            if max_diff > 25:
                os.remove("sentinel_2/" + filename)
                os.remove("sentinel_2" + filename[:-3] + "png")

    band_data = []

    for filename in os.listdir('sentinel_2'):
        if filename.endswith('.npz'):
            file = dict(np.load('sentinel_2/' + filename))
            for key in file.keys():
                if key in ['B01', 'B09']:
                    band_data.append(crop(file[key], min_10))
                elif key in ['B02', 'B03', 'B04', 'B08']:
                    band_data.append(crop(file[key], min_20))
                elif key in ['B05', 'B06', 'B07', 'B8A', 'B09', 'B11', 'B12']:
                    band_data.append(crop(file[key], min_60))
                else:
                    raise Exception("Invalid key")
                
            np.savez(
            f"sentinel_2/{filename}",
            **{band: data for band, data in zip(bands, band_data)}
            )

def inspect_data():
    for filename in os.listdir('sentinel_2'):
        if filename.endswith('.npz.npz'):
            file = np.load('sentinel_2/' + filename)
            print(filename, np.shape(file['B01']))

def main():
    download_data()
    # crop_data()
    # inspect_data()

if __name__ == "__main__":
    main()