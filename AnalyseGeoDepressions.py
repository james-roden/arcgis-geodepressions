# -----------------------------------------------
# Name: Pockmark Detection: Analyse Geo-Depressions
# Purpose: Semi-automated characterisation of pockmarks/Analyse geo-depressions from IdentifyGeoDepressions tool
# Author: James M Roden
# Created: July 2017
# ArcGIS Version: 10.3
# ArcGIS Licence Requirements: Spatial Analyst
# Python Version 2.6
# PEP8
# -----------------------------------------------

try:
    import arcpy
    import sys
    import traceback
    import math
    import os

    # Custom exceptions for spatial analysis license and bath with negative values only
    class LicenseError(Exception):
        pass

    class NotNegative(Exception):
        pass

    # Azimuth function
    def azimuth(coords):
        """
        Return azimuthal bearing relative to north

        Keyword arguments:
        coords -- list of coordinates x1, x2, y1, y2
        """

        radians = math.atan2((coords[1] - coords[0]), (coords[3] - coords[2]))
        degrees = (radians * 180) / math.pi
        if degrees < 0:
            degrees += 180
        return degrees

    # Eccentricity function
    def eccentricity(major_axis, minor_axis):
        """
        Returns eccentricity of 2 axis

        Keyword arguments:
        major_axis -- major axis of shape (int or float)
        minor_axis -- minor axis of shape (int of float)
        """

        return math.sqrt(((float(major_axis) ** 2) - (float(minor_axis) ** 2)) / (float(major_axis) ** 2))

    # Thinness ratio function
    def thinness_ratio(area, perimeter):
        """
        Returns the thinness ratio, given area and perimeter of shape

        Keyword arguments:
        area      -- area of shape
        perimeter -- perimeter of shape
        """

        return (4 * math.pi) * (area / (perimeter ** 2))

    # Morphological feature descriptor
    def shape_descriptor(poly_thinness, poly_dd_ratio):
        """
        Returns generic description of polygon shape

        Keyword arguments:
        poly_thinness       -- thinness ratio of polygon
        poly_dd_ratio       -- diameter/depth ratio of polygon
        """

        if poly_thinness < 0.5 or poly_dd_ratio > 100:
            return "Irregular shape and/or low dia/dep ratio. Unlikely to be caused by fluid escape"
        elif poly_thinness < 0.75:
            return "Semi-regular shape. Depression needs further investigation"
        else:
            return "Regular shape. Potentially a geo-feature caused by fluid escape"

    def diameter_depth_ratio(diameter, depth):
        """
        Returns depth:diameter ratio

        Keyword arguments:
        diameter   -- average diamater of polygon
        depth      -- depth of polygon
        """

        return abs(diameter/depth)

    # arcpy environment settings
    arcpy.env.workspace = r"in_memory"
    arcpy.env.scratchWorkspace = r"in_memory"
    arcpy.env.overwriteOutput = True

    # ArcGIS tool parameters
    raster_layer = arcpy.GetParameterAsText(0)
    depression_polygons = arcpy.GetParameter(1)
    output = arcpy.GetParameterAsText(2)

    # Check if bathy is negative values only
    # Create raster object from layer (or full path data set)
    describe = arcpy.Describe(raster_layer)
    raster_source = os.path.join(describe.path, os.path.basename(raster_layer))
    bathy_dataset = arcpy.Raster(raster_source)
    maximum_value = bathy_dataset.maximum
    arcpy.AddMessage("Bathy statistics calculated.")
    if float(maximum_value) > 0:
        raise NotNegative

    if float(maximum_value) > 0:
        raise NotNegative

    # Check out Spatial Analyst extension if available
    if arcpy.CheckExtension("spatial") == "Available":
        arcpy.CheckOutExtension("spatial")
        arcpy.AddMessage("Spatial Analyst extension successfully checked out.")
    else:
        # Raise custom error
        raise LicenseError

    # Calculate deepest point of depression
    # Use 32 bit epsilon value to avoid float numbers issues
    zonal_min = arcpy.sa.ZonalStatistics(depression_polygons, "FID", bathy_dataset, statistics_type="MINIMUM",
                                         ignore_nodata="DATA")
    zonal_max = arcpy.sa.ZonalStatistics(depression_polygons, "FID", bathy_dataset, statistics_type="MAXIMUM",
                                         ignore_nodata="DATA")
    depression_depth = arcpy.sa.Con((abs((abs(zonal_max - bathy_dataset))-(abs(zonal_max - zonal_min)))) < 0.001,
                                    (abs(zonal_max - zonal_min)))
    deepest_point = arcpy.RasterToPoint_conversion(depression_depth, None, "VALUE")
    arcpy.AddMessage("Deepest point located.")

    # Extract bathymetry depth value to deepest point
    arcpy.sa.ExtractMultiValuesToPoints(deepest_point, [[bathy_dataset, "DEPTH"]], "NONE")

    # Add fields to depression polygons for calculations
    float_fields = ["MAJ_AXIS", "MIN_AXIS", "ECC", "AZIMUTH", "THIN_RAT", "PERIMETER", "AREA_M", "DIDP_RAT"]
    for field in float_fields:
        arcpy.AddField_management(depression_polygons, field, "FLOAT")
    # Add morphological characteristics and azimuth field.
    arcpy.AddField_management(depression_polygons, "MORP_CHAR", "TEXT", field_length=80)
    arcpy.AddField_management(depression_polygons, "DEP_ID", "SHORT")

    # Smooth depression polygons
    describe = arcpy.Describe(bathy_dataset)
    cell_size = describe.meanCellWidth
    min_area = (cell_size * 2) ** 2
    tolerance = cell_size * 3
    depression_polygons = arcpy.SmoothPolygon_cartography(depression_polygons, None, "PAEK", tolerance, "NO_FIXED")
    arcpy.AddMessage("Polygons smoothed.")

    # Calculate major axis, minor axis, azimuth, and eccentricity fields
    with arcpy.da.UpdateCursor(depression_polygons, ["SHAPE@", "DEP_ID", "AREA_M", "PERIMETER", "MAJ_AXIS", "MIN_AXIS",
                                                     "ECC", "AZIMUTH", "THIN_RAT", "MORP_CHAR", "DIDP_RAT",
                                                     "POCK_DEP"]) as cursor:
        dep_id = 1
        for row in cursor:
            shape_object = row[0]
            row[1] = dep_id
            row[2] = shape_object.area
            row[3] = shape_object.length
            x1, y1, x2, y2, x3, y3, x4, y4 = [float(coord) for coord in shape_object.hullRectangle.split(" ")]
            distance1 = math.hypot((x1 - x2), (y1 - y2))
            distance2 = math.hypot((x2 - x3), (y2 - y3))
            if distance1 <= distance2:
                min_axis = distance1
                maj_axis = distance2
                azimuth_coords = [x2, x3, y2, y3]
            else:
                min_axis = distance2
                maj_axis = distance1
                azimuth_coords = [x1, x2, y1, y2]

            row[4] = maj_axis
            row[5] = min_axis
            row[6] = eccentricity(maj_axis, min_axis)
            row[7] = azimuth(azimuth_coords)
            row[8] = thinness_ratio(row[2], row[3])
            average_diameter = (row[4] + row[5]) / 2
            row[10] = diameter_depth_ratio(average_diameter, row[11])
            row[9] = shape_descriptor(row[8], row[10])
            cursor.updateRow(row)
            dep_id += 1
        del cursor

    arcpy.AddMessage("Area, perimeter, major axis, minor axis, eccentricity, azimuth, diamater/depth ratio"
                     "and thinness ratio calculated.")

    # Field Mappings for spatial join
    # Create field mapping for depression polygons
    fields = ["POCK_DEP", "DEP_ID", "MAJ_AXIS", "MIN_AXIS", "ECC", "AZIMUTH", "THIN_RAT", "AREA_M", "PERIMETER",
              "MORP_CHAR"]
    field_maps = [arcpy.FieldMap() for i in range(10)]
    field_mappings = arcpy.FieldMappings()
    for fm, f in zip(field_maps, fields):
        fm.addInputField(depression_polygons, f)
        field_mappings.addFieldMap(fm)

    # Join depression polygons attributes to deepest point
    deepest_point = arcpy.SpatialJoin_analysis(deepest_point, depression_polygons, None, field_mapping=field_mappings)
    arcpy.AddMessage("Deepest point and depression polygon spatial Join Completed.")

    # Clean Up. Delete unwanted fields and remove duplicate deepest points
    # --------------
    arcpy.DeleteField_management(depression_polygons, ["TARGET_FID", "Join_Count"])
    arcpy.DeleteField_management(deepest_point, ["TARGET_FID", "Join_Count"])
    arcpy.DeleteIdentical_management(deepest_point, ["DEP_ID"])
    # ---------------

    # Create depression polygon centre point
    centroid_point = arcpy.FeatureToPoint_management(depression_polygons, None, "INSIDE")
    arcpy.AddMessage("Centroid point created.")

    # Path variables
    polygon_path = os.path.join(output, "Depression_Polygons")
    deepest_point_path = os.path.join(output, "Depression_Deepest_Point")
    centroid_point_path = os.path.join(output, "Depression_Centroid")
    paths = [polygon_path, deepest_point_path, centroid_point_path]

    # Save output features
    arcpy.CopyFeatures_management(depression_polygons, polygon_path)
    arcpy.CopyFeatures_management(deepest_point, deepest_point_path)
    arcpy.CopyFeatures_management(centroid_point, centroid_point_path)

    # --------------------------------------
    # Optional Symbology, comment out if not needed
    # --------------------------------------

    try:
        # If script is run from MXD, the following code executes. Adds symbology to the 3 outputs and adds them to TOC.
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = mxd.activeDataFrame
        file_dir = os.path.dirname(__file__)
        polygon_symbol = os.path.join(file_dir, "polygon.lyr")
        deepest_point_symbol = os.path.join(file_dir, "deep.lyr")
        centroid_point_symbol = os.path.join(file_dir, "centroid.lyr")
        symbols = [polygon_symbol, deepest_point_symbol, centroid_point_symbol]

        # Check if workspace is folder and add shapefile extension
        desc = arcpy.Describe(output)
        if desc.workspaceType == "FileSystem":
            paths = [path + ".shp" for path in paths]

        for path, symbol in zip(paths, symbols):
            layer = arcpy.mapping.Layer(path)
            arcpy.ApplySymbologyFromLayer_management(layer, symbol)
            arcpy.mapping.AddLayer(df, layer, "TOP")

    except Exception:
        arcpy.AddMessage("Symbology not added.")
        pass

    # ---------------------------------------
    # End of optional symbology
    # ---------------------------------------

    arcpy.AddMessage("GeoDepression analysis complete.")

except LicenseError:
    error = "Spatial Analyst Extension Unavailable."
    arcpy.AddError(error)
    print error

except NotNegative:
    error = "Bathy raster must be negative values only."
    arcpy.AddError(error)
    print error

except:
    e = sys.exc_info()[1]
    arcpy.AddError(e.args[0])
    tb = sys.exc_info()[2]  # Traceback object
    tbinfo = traceback.format_tb(tb)[0]  # Traceback string
    # Concatenate error information and return to GP window
    pymsg = ('PYTHON ERRORS:\nTraceback info:\n' + tbinfo + '\nError Info: \n'
             + str(sys.exc_info()[1]))
    msgs = 'ArcPy ERRORS:\n' + arcpy.GetMessages() + '\n'
    arcpy.AddError(msgs)
    print pymsg

finally:
    # Check in spatial analysis extension
    arcpy.CheckInExtension("spatial")
    arcpy.AddMessage("Spatial analysis extension checked in.")

    # Delete in_memory
    arcpy.Delete_management('in_memory')
    arcpy.AddMessage("in_memory intermediate files deleted.")

# End of script
