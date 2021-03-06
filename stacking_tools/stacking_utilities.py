# Stacking Utilities

import os, sys, glob
import datetime as dt
import matplotlib
# matplotlib.use('Agg')
import matplotlib.cm as cm
import matplotlib.pyplot as plt
import numpy as np
import re
from read_write_insar_utilities import isce_read_write
from Tectonic_Utils.read_write import netcdf_read_write
import readmytupledata
from intf_generating import get_ra_rc_from_ll, sentinel_utilities
from Tectonic_Utils.geodesy import haversine


def read_baseline_table(baseline_file):
    # Returns a list of tuples of datetimes and baseline values
    # Example: (150.2, dt, 2015230)...
    if baseline_file == '':
        print("Error! No baseline file provided in stacking.config. Exiting...");
        sys.exit(0);
    [_, times, baselines, _] = sentinel_utilities.read_baseline_table(baseline_file);
    dtarray = []; datestrs = [];
    for i in range(len(times)):
        dtarray.append(dt.datetime.strptime(str(int(times[i] + 1)), '%Y%j'));
        datestrs.append(str(times[i] + 1)[0:7]);   # string with format "2014361"

    # Re-order times and baselines in chronological order
    baselines = [x for _, x in sorted(zip(dtarray, baselines))];
    datestrs = [x for _, x in sorted(zip(dtarray, datestrs))];
    dtarray = sorted(dtarray);
    baseline_tuple_list = [];
    for i in range(len(baselines)):
        baseline_tuple_list.append((baselines[i], dtarray[i], datestrs[i]));
    return baseline_tuple_list;


def get_list_of_intf_all(config_params, returnval='all'):
    # This is mechanical: just takes the list of interferograms in intf_all. 
    # It is designed to work with both ISCE and GMTSAR files.
    # The more advanced selection takes place in make_selection_of_intfs.
    # By Default, returns a list of tuples like : (dt1, dt2, intf_file, corr_file).
    # If returnval is set, it can return a subset like a list of intf_filenames.
    if config_params.SAT == "S1":
        total_intf_list = glob.glob(config_params.intf_dir + "/???????_???????/"+config_params.intf_filename);
        total_corr_list = glob.glob(config_params.intf_dir + "/???????_???????/"+config_params.corr_filename);
        intf_file_tuples = get_intf_datetuple_gmtsar(total_intf_list, total_corr_list);
    elif config_params.SAT == "UAVSAR":
        # Specific to the case of UAVSAR stacks with alt-unwrapped taking place
        total_intf_list = glob.glob("../Igrams/*/alt_unwrapped/filt*_fully_processed.uwrappedphase");
        total_corr_list = glob.glob("../Igrams/*/alt_unwrapped/filt*_fully_processed.cor");
        intf_file_tuples = get_intf_datetuple_isce(total_intf_list, total_corr_list);
    else:
        total_intf_list, total_corr_list = [], [];
        intf_file_tuples = [];
    print("Identifying all unwrapped intfs in %s: " % config_params.intf_dir);
    print("  Found %d interferograms for stacking. " % (len(total_intf_list)));
    print("  Found %d coherence files for stacking. " % (len(total_corr_list)));
    if len(total_intf_list) != len(total_corr_list):
        print("ERROR!  Length of intfs does match length of coherence files!  Please fix this before proceeding. \n");
        sys.exit(1);
    if returnval == 'intf_file':
        intf_files = [x[2] for x in intf_file_tuples];
        return intf_files;
    else:
        return intf_file_tuples;


# Turn interferograms into date-date-filename tuples
def get_intf_datetuple_gmtsar(total_intf_list, total_corr_list):
    intf_tuple_list = [];
    for i in range(len(total_intf_list)):
        datesplit = re.findall(r"\d\d\d\d\d\d\d_\d\d\d\d\d\d\d", total_intf_list[i])[0];  # example: 2010040_2014064
        date1 = dt.datetime.strptime(str(int(datesplit[0:7]) + 1), "%Y%j");
        date2 = dt.datetime.strptime(str(int(datesplit[8:15]) + 1), "%Y%j");  # adding 1 because 000 = January 1
        intf_tuple_list.append((date1, date2, total_intf_list[i], total_corr_list[i]));
    return intf_tuple_list;


def get_intf_datetuple_isce(total_intf_list, total_corr_list):
    intf_tuple_list = [];
    for i in range(len(total_intf_list)):
        datesplit = re.findall(r"\d\d\d\d\d\d\d\d_\d\d\d\d\d\d\d\d", total_intf_list[i])[0];  # ex: 20100402_20140304
        date1 = dt.datetime.strptime(datesplit[0:8], "%Y%m%d");
        date2 = dt.datetime.strptime(datesplit[9:17], "%Y%m%d");
        intf_tuple_list.append((date1, date2, total_intf_list[i], total_corr_list[i]));
    return intf_tuple_list;


def get_xdates_from_intf_tuple_dates(date_pairs_dt):
    total_dates = [];
    for item in date_pairs_dt:
        total_dates.append(item[0]);
        total_dates.append(item[1]);
    xdates = sorted(set(total_dates));
    return xdates;


# Reference Pixel Math
def get_ref_index(ref_loc, ref_idx, geocoded_flag, intf_files):
    # Get the index of the reference pixel (generally using merged-subswath files)
    # If you don't have the reference pixel in the config file, 
    # the program will stop execution so you can write it there.
    # intf_files are a list of tuples of (dt, dt, filename, filename)
    print("Identifying reference pixel:");
    if ref_idx == "" and ref_loc == "":
        get_100p_pixels_manually_choose(intf_files);
        sys.exit(0);
    elif ref_idx != "":  # First preference: Get the reference pixel index from the config file
        rowref = int(ref_idx.split('/')[0])
        colref = int(ref_idx.split('/')[1])
        print("  Found rowref, colref = %d, %d from config file.\n  Moving on..." % (rowref, colref));
    else:  # here we have a reference pixel from lat/lon
        lon = float(ref_loc.split('/')[0])
        lat = float(ref_loc.split('/')[1])
        if geocoded_flag:   # Second preference: Extract the lat/lon from already-geocoded intf_files
            rowref, colref = get_reference_pixel_from_geocoded_grd(lon, lat, intf_files[0][2]);
            # Would use uavsar_from_lonlat_get_rowcol if doing UAVSAR here.
        else:  # Last preference: Extract the lat/lon from radar coordinates using trans.dat of merged-subswath files
            trans_dat = "merged/trans.dat";
            rowref, colref = get_referece_pixel_from_radarcoord_grd(lon, lat, trans_dat, intf_files[0][2]);
        print("\nSTOP! Please write the reference row/col %d/%d into your config file. \n" % (rowref, colref))
        sys.exit(1);
    return rowref, colref;


def get_100p_pixels_manually_choose(filenameslist):
    # This iterative function helps you manually choose a reference pixel.
    # You might have to run through this function a number of times
    # To select your boxes and your eventual reference pixel.
    # I pick one in a stable area, outside of the deformation, ideally in a desert.

    print("Finding the pixels that are 100 percent coherent");
    # Finding pixels that are completely non-nan
    mydata = readmytupledata.reader_isce(filenameslist, band=2);
    total_pixels = np.shape(mydata.zvalues)[1] * np.shape(mydata.zvalues)[2];
    total_images = np.shape(mydata.zvalues)[0];
    count = 0;
    ypixels_good, xpixels_good = [], [];
    ypixels_options, xpixels_options = [], [];

    for i in range(np.shape(mydata.zvalues)[1]):
        for j in range(np.shape(mydata.zvalues)[2]):
            oneslice = mydata.zvalues[:, i, j];
            if np.sum(~np.isnan(oneslice)) == total_images:  # if we have perfect coherence
                count = count + 1;
                xpixels_good.append(j);
                ypixels_good.append(i);
                # Here we will adjust parameters until we find a reference pixel that we like.
                if 280 < j < 300 and 2500 < i < 2700:
                    xpixels_options.append(j);
                    ypixels_options.append(i);

    idx_lucky = 710;
    xref = xpixels_options[idx_lucky];
    yref = ypixels_options[idx_lucky];

    print("%d of %d (%f percent) are totally coherent. " % (count, total_pixels, 100 * (count / total_pixels)));
    print(np.shape(mydata.zvalues));
    print("%d pixels are good options for the reference pixel. " % (len(xpixels_options)));

    # Make a plot that shows where those pixels are
    # a=rwr.read_grd(outdir+'/signalspread_cut.nc');
    plt.figure();
    # plt.imshow(a,aspect=1/4, cmap='rainbow');
    plt.plot(xpixels_good, ypixels_good, '.', color='k');
    plt.plot(xpixels_options, ypixels_options, '.', color='g');
    plt.plot(xref, yref, '.', color='r');
    plt.savefig('best_pixels.png');
    plt.close();

    print("Based on 100p pixels, selecting reference pixel at row/col %d, %d " % (yref, xref));
    print("STOPPING ON PURPOSE: Please write your reference pixel in your config file.");

    return yref, xref;


def uavsar_from_lonlat_get_rowcol(config_params):
    # An alternative way of choosing a reference pixel with UAVSAR files
    # Given a ref loc, get the geocoded grids and find the nearest point.
    # Return its row and column.
    # Step 1: Geocode properly based on a sample interferogram grid (done)
    # Step 2: extract nearest pixel (code in Brawley repo)

    # isce_geocode_tools.geocode_UAVSAR_stack(config_params, 'geocoded');

    reflon = float(config_params.ref_loc.split(',')[0]);
    reflat = float(config_params.ref_loc.split(',')[1]);
    # Next we get the nearest pixel from the rasters
    raster_lon = isce_read_write.read_scalar_data(config_params.ts_output_dir + "/cut_lon.gdal");
    raster_lat = isce_read_write.read_scalar_data(config_params.ts_output_dir + "/cut_lat.gdal");
    i_found, j_found = get_nearest_pixel_in_raster(raster_lon, raster_lat, reflon, reflat);
    print("From lon/lat, found Row and Column at %d, %d " % (i_found, j_found));
    print("STOPPING ON PURPOSE: Please write your reference pixel in your config file.");
    return i_found, j_found;


def get_nearest_pixel_in_raster(raster_lon, raster_lat, target_lon, target_lat):
    # A very general function
    # Take a 2D raster of lons and lats and find the grid location closest to the target location
    dist = np.zeros(np.shape(raster_lon));
    lon_shape = np.shape(raster_lon);
    for i in range(lon_shape[0]):
        for j in range(lon_shape[1]):
            mypt = [raster_lat[i][j], raster_lon[i][j]];
            dist[i][j] = haversine.distance((target_lat, target_lon), mypt);
    minimum_distance = np.nanmin(dist);
    if minimum_distance < 0.25:  # if we're inside the domain.
        idx = np.where(dist == np.nanmin(dist));
        i_found = idx[0][0];
        j_found = idx[1][0];
        print(raster_lon[i_found][j_found], raster_lat[i_found][j_found]);
    else:
        i_found = -1;
        j_found = -1;  # error codes
    return i_found, j_found;


def get_referece_pixel_from_radarcoord_grd(lon, lat, trans_dat, example_grd):
    print("  Finding coordinate %.4f, %.4f in radarcoord grd file %s" % (lon, lat, trans_dat));
    [ra, az] = get_ra_rc_from_ll.get_ra_from_ll(trans_dat, example_grd, lon, lat);
    if np.isnan(ra) or np.isnan(az):
        print("WARNING: Cannot Find %f %f in file." % (lon, lat));
        rowref = np.nan;
        colref = np.nan;
    else:
        [rowref, colref] = get_ra_rc_from_ll.get_nearest_row_col(example_grd, ra, az);
        print("  Found Coordinate at row, col %d, %d " % (rowref, colref));
    return rowref, colref;


def get_reference_pixel_from_geocoded_grd(ref_lon, ref_lat, ifile):
    # Find the nearest pixel to a reference point in a geocoded grid
    print("  Finding coordinate %.4f, %.4f in geocoded interferograms %s" % (ref_lon, ref_lat, ifile) );
    [xdata, ydata, _] = netcdf_read_write.read_netcdf4(ifile);
    if xdata[0] > 180:   # If numbers are in the range above 180, turn them into -180 to 180
        xdata = [i-360 for i in xdata];
    row_idx = np.argmin(np.abs(np.array(ydata) - ref_lat));
    col_idx = np.argmin(np.abs(np.array(xdata) - ref_lon));
    if row_idx == 0 or row_idx == len(ydata) or col_idx == 0 or col_idx == len(xdata):
        print("WARNING: Coordinate %f %f may be near edge of domain." % (ref_lon, ref_lat) );
        row_idx = np.nan;
        col_idx = np.nan; 
    print("  Found Coordinates at row/col: %d/%d " % (row_idx, col_idx));
    return row_idx, col_idx;


# Exclude and Include criteria
def exclude_intfs_manually(total_intf_tuple, skip_file):
    print("Excluding intfs based on manual_exclude file %s." % skip_file);
    print(" Started with %d total interferograms. " % (len(total_intf_tuple)));
    select_intf_tuple = [];
    manual_removes = [];
    if skip_file == "":
        print(" No manual exclude file provided.\n Returning all %d interferograms. " % (len(total_intf_tuple)));
        select_intf_tuple = total_intf_tuple;
    else:
        print(" Excluding the following interferograms based on SkipFile %s: " % skip_file);
        ifile = open(skip_file, 'r');
        for line in ifile:
            manual_removes.append(line.split()[0]);
        ifile.close();
        print(manual_removes);

        if not manual_removes:
            select_intf_tuple = total_intf_tuple;
        else:
            # Checking to see if each interferogram should be included. 
            for igram in total_intf_tuple:
                include_flag = 1;
                for scene in manual_removes:
                    if scene in igram[2]:
                        include_flag = 0;
                if include_flag == 1:
                    select_intf_tuple.append(igram);
        print(" Returning %d interferograms " % len(select_intf_tuple));
    return select_intf_tuple;


def include_only_coseismic_intfs(total_intf_tuple, coseismic):
    # Implements a filter for spanning a coseismic interval, if you include one. 
    select_intf_tuple = [];
    if coseismic == "":
        return total_intf_tuple;
    else:
        print("Returning only interferograms that cross coseismic event at %s " % (
            dt.datetime.strftime(coseismic, "%Y-%m-%d")))
        for mytuple in total_intf_tuple:
            if mytuple[0] < coseismic < mytuple[1]:
                select_intf_tuple.append(mytuple);  # in the case of a coseismic constraint    
        print(" Returning %d interferograms " % len(select_intf_tuple));
        return select_intf_tuple;


def include_intfs_by_time_range(total_intf_tuple, start_time, end_time):
    # Here, we look for each interferogram that falls totally within the time range 
    # given in the config file.
    if start_time == "" and end_time == "":
        return total_intf_tuple;
    print("Including only interferograms in time range %s to %s." % (dt.datetime.strftime(start_time, "%Y-%m-%d"),
                                                                     dt.datetime.strftime(end_time, "%Y-%m-%d")));
    print(" Starting with %d interferograms " % len(total_intf_tuple))
    select_intf_tuple = [];
    for mytuple in total_intf_tuple:
        if start_time <= mytuple[0] <= end_time:
            if start_time <= mytuple[1] <= end_time:
                select_intf_tuple.append(mytuple);  # in the case of no coseismic constraint
    print(" Returning %d interferograms " % len(select_intf_tuple));
    return select_intf_tuple;


def include_timeinterval_intfs(total_intf_tuple, intf_timespan):
    # Only include interferograms of a certain time interval (such as shorter than one year, or longer than one year);
    # intf_timespan is a string with the format '300+' for longer than 300 days etc.
    if intf_timespan == "":
        return total_intf_tuple;
    select_intf_tuple = [];
    if intf_timespan[-1] == '+':
        criterion = 'longer'
    else:
        criterion = 'shorter'
    days = int(intf_timespan[0:-1]);
    print("Only including interferograms %s than %d days " % (criterion, days));
    for mytuple in total_intf_tuple:
        datedelta = (mytuple[1] - mytuple[0]).days;
        if criterion == "longer":
            if datedelta > days:
                select_intf_tuple.append(mytuple);
        else:
            if datedelta < days:
                select_intf_tuple.append(mytuple);
    print(" Returning %d interferograms " % len(select_intf_tuple));
    return select_intf_tuple;


def write_intf_record(intf_tuple_list, record_file):
    print("Writing out list of %d interferograms used in this run to %s" % (len(intf_tuple_list), record_file));
    ofile = open(record_file, 'w');
    ofile.write("List of %d interferograms used in this run:\n" % (len(intf_tuple_list)));
    for mytuple in intf_tuple_list:
        ofile.write("%s\n" % (mytuple[2]));
    ofile.close();
    return;


def make_selection_of_intfs(config_params):
    # ------------------------------ # 
    # HERE IS WHERE YOU SELECT WHICH INTERFEROGRAMS YOU WILL BE USING.
    # WE MIGHT APPLY A MANUAL EXCLUDE, OR A TIME CONSTRAINT. 
    # THIS DEPENDS ON YOUR CONFIG SETTINGS
    # ------------------------------ # 
    # The working internal intf_tuple is: (d1, d2, intf_filename, corr_filename)
    intf_tuples = get_list_of_intf_all(config_params);

    # Use the config file to excluse certain time ranges and implement coseismic constraints
    select_intf_tuples = include_intfs_by_time_range(intf_tuples, config_params.start_time, config_params.end_time);
    select_intf_tuples = include_only_coseismic_intfs(select_intf_tuples, config_params.coseismic);

    # Do you only want to include long or short interferograms? 
    select_intf_tuples = include_timeinterval_intfs(select_intf_tuples, config_params.intf_timespan);

    # Manual Excludes? 
    select_intf_tuples = exclude_intfs_manually(select_intf_tuples, config_params.skip_file);

    # Writing the exact interferograms used in this run, and returning file names. 
    write_intf_record(select_intf_tuples, config_params.ts_output_dir+"/intf_record.txt")
    select_intf_list = [mytuple[2] for mytuple in select_intf_tuples]
    select_corr_list = [mytuple[3] for mytuple in select_intf_tuples]
    return select_intf_list, select_corr_list, select_intf_tuples;


# Metrics and Connected Components
def make_igram_stick_plot(intf_file_tuples, ts_output_dir):
    print("Making simple plot of interferograms used.")
    plt.figure(dpi=300, figsize=(8, 7));
    for i in range(len(intf_file_tuples)):
        plt.plot([intf_file_tuples[i][0], intf_file_tuples[i][1]], [i, i], '.', markersize=7, linestyle=None,
                 color='gray');
        plt.plot([intf_file_tuples[i][0], intf_file_tuples[i][1]], [i, i], markersize=5);
    plt.title(str(len(intf_file_tuples)) + ' Interferograms Used');
    plt.xlabel('Time');
    plt.ylabel('Interferogram Number');
    plt.savefig(ts_output_dir + "/intf_record.png");
    return;


def check_clean_computation(rowref, colref, mytuple, signal_spread_data):
    # This function checks the number of interferograms present in the reference pixel.
    # It can possibly do other defensive checks as well.
    ref_pixel_values = mytuple.zvalues[:, rowref, colref];
    num_nans = np.sum(np.isnan(ref_pixel_values));
    num_intfs = len(ref_pixel_values);
    if num_nans / num_intfs > 0.5:
        print("Error! Data Cube has more than 50% NaNs for your reference pixel. What do you want to do?  ");
        sys.exit(0);
    reference_ss = signal_spread_data[rowref, colref];
    print("Intf Stack has %f percent non-nan interferograms for ref pixel %d, %d" % (100*num_nans/num_intfs, rowref, colref) )
    print("Signal Spread has %f percent coherent igrams for ref pixel %d, %d" % (reference_ss, rowref, colref) );
    if signal_spread_data[rowref, colref] < 50:
        print("Error! Reference Pixel has less than 50% coherent interferograms. What do you want to do? ");
        sys.exit(0);
    return;


def report_on_refpixel(rowref, colref, signal_spread_data, outdir):
    ofile = open(outdir+"/metrics_report.txt", 'w');
    ofile.write("Refpixel is Row/col %d %d \n" % (rowref, colref) );
    ofile.write("Percentage of good interferograms at that pixel: %f \n" % signal_spread_data[rowref, colref]);
    ofile.close();
    return;


def find_connected_dates(date_pairs, sample_date):
    connected_dates = [];
    for i in range(len(date_pairs)):
        if date_pairs[i][0:7] == sample_date:
            connected_dates.append(date_pairs[i][8:15]);
        if date_pairs[i][8:15] == sample_date:
            connected_dates.append(date_pairs[i][0:7]);
    return connected_dates;


def connected_components_search(date_pairs, datestrs):
    # Are we inverting a complete network?
    # This function will catch both 'disconnected networks' and 'bad day' cases.
    # We want only one connected component with len==len(datestrs).
    # Otherwise the network should fail.
    # 1. initialize the queue with the first date
    # 2. find anything connected to that date, add to the queue.
    # 3. When all of the dates connected to the first date have been added to queue, pop the first date from queue
    # 4. Repeat until the queue is gone.
    # 5. See if all dates have been added to the component.

    # Initializing first time through
    label = np.zeros(np.shape(datestrs));
    queue = [datestrs[0]];

    # some kind of loop
    while len(queue) > 0:
        sample_date = queue[0];  # go exploring the queue, starting at the front.
        idx_sample = datestrs.index(sample_date);
        label[idx_sample] = 1;
        connected_dates = find_connected_dates(date_pairs, sample_date);
        for i in range(len(connected_dates)):
            idx_connection = datestrs.index(connected_dates[i]);
            if label[idx_connection] == 0:
                label[idx_connection] = 1;
                queue.append(connected_dates[i]);
        queue.pop(0);  # removing the point from the queue after it has been traversed

    return np.sum(label) == len(datestrs);  # returning SUCCESS if we have a single cc touching every required date


# Functions to get TS points in row/col coordinates
def drive_cache_ts_points(ts_points_file, intf_file_example, geocoded_flag):
    # If you want to re-compute things, you need to delete the cache. 
    if os.path.isfile(ts_points_file + ".cache"):
        lons, lats, names, rows, cols = read_ts_points_file(ts_points_file + ".cache");
    elif os.path.isfile(ts_points_file):  # if there's no cache, we will make one.
        lons, lats, names, rows, cols = read_ts_points_file(ts_points_file);
        lons, lats, names, rows, cols = match_ts_points_row_col(lons, lats, names, rows, cols,
                                                                intf_file_example, geocoded_flag);
        write_ts_points_file(lons, lats, names, rows, cols, ts_points_file + ".cache");
    else:
        print(
            "Error! You ask for points but there's no ts_points_file %s . No points computed. " % ts_points_file);
        return None, None, None, None, None;
    return lons, lats, names, rows, cols;


def match_ts_points_row_col(lons, lats, names, rows, cols, example_grd, geocoded_flag):
    # Find each row and col that hasn't been found before, either in geocoded or radarcoords. 
    trans_dat = "merged/trans.dat";
    for i in range(len(lons)):
        if rows[i] == '':
            if geocoded_flag:
                irow, icol = get_reference_pixel_from_geocoded_grd(lons[i], lats[i], example_grd);
            else:
                irow, icol = get_referece_pixel_from_radarcoord_grd(lons[i], lats[i], trans_dat, example_grd);
            rows[i] = irow;
            cols[i] = icol;
    return lons, lats, names, rows, cols;


def read_ts_points_file(ts_points_file):
    # Here we can use several formats simultaneously. Point name is required. 
    # Format 1:  -117.76 35.88 313 654 coso1
    # Format 2:  -117.76 35.90 coso2
    print("Reading file %s" % ts_points_file);
    lons, lats, names, rows, cols = [], [], [], [], [];
    ifile = open(ts_points_file, 'r');
    for line in ifile:
        temp = line.split();
        if len(temp) == 3:  # we have provided the lat/lon/name
            lons.append(float(temp[0]));
            lats.append(float(temp[1]));
            names.append(temp[2]);
            rows.append('');
            cols.append('');
        if len(temp) == 5:  # we have provided the lat/lon/row/col/name
            if np.isnan(float(temp[2])):  # if the cache has nan for those pixels, we skip. 
                continue;
            else:
                lons.append(float(temp[0]));
                lats.append(float(temp[1]));
                rows.append(int(temp[2]));
                cols.append(int(temp[3]));
                names.append(temp[4]);
    print("  Computing time series at %d geographic points " % (len(lons)));
    return lons, lats, names, rows, cols;


# Output Functions
def write_ts_points_file(lons, lats, names, rows, cols, ts_points_file):
    print("Writing %s " % ts_points_file);
    ofile = open(ts_points_file, 'w');
    for i in range(len(lons)):
        ofile.write("%.5f %.5f %s %s %s\n" % (lons[i], lats[i], str(rows[i]), str(cols[i]), names[i]));
    ofile.close();
    return;


def get_axarr_numbers(cols, idx):
    # Given an incrementally counting idx number and a subplot dimension, where is our plot? 
    # total_plots = rows * cols;
    col_num = np.mod(idx, cols);
    row_num = int(np.floor(idx / cols));
    return row_num, col_num;


def plot_full_timeseries(TS_NC_file, xdates, TS_image_file, vmin=-50, vmax=200, aspect=1):
    # Make a nice time series plot. 
    tdata, xdata, ydata, TS_array = netcdf_read_write.read_3D_netcdf(TS_NC_file);
    num_rows_plots = 3;
    num_cols_plots = 4;

    f, axarr = plt.subplots(num_rows_plots, num_cols_plots, figsize=(16, 10), dpi=300);
    for i in range(len(xdates)):
        rownum, colnum = get_axarr_numbers(num_cols_plots, i);
        axarr[rownum][colnum].imshow(TS_array[i, :, :], aspect=aspect, cmap='rainbow', vmin=vmin, vmax=vmax);
        titlestr = dt.datetime.strftime(xdates[i], "%Y-%m-%d");
        axarr[rownum][colnum].get_xaxis().set_visible(False);
        axarr[rownum][colnum].set_title(titlestr, fontsize=20);

    _ = f.add_axes([0.75, 0.35, 0.2, 0.3], visible=False);
    color_boundary_object = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax);
    custom_cmap = cm.ScalarMappable(norm=color_boundary_object, cmap='rainbow');
    custom_cmap.set_array(np.arange(vmin, vmax));
    cb = plt.colorbar(custom_cmap, aspect=12, fraction=0.2, orientation='vertical');
    cb.set_label('Displacement (mm)', fontsize=18);
    cb.ax.tick_params(labelsize=12);

    plt.savefig(TS_image_file);
    return;


def plot_incremental_timeseries(TS_NC_file, xdates, TS_image_file, vmin=-50, vmax=200, aspect=1):
    # Make a nice time series plot. 
    # With incremental displacement data. 
    tdata, xdata, ydata, TS_array = netcdf_read_write.read_3D_netcdf(TS_NC_file);
    num_rows_plots = 3;
    num_cols_plots = 4;

    # Combining the two shortest intervals into one. 
    print(np.shape(TS_array));
    selected = [0, 1, 3, 4, 5, 6, 7, 8, 9, 10];
    TS_array = TS_array[selected, :, :];
    xdates = [xdates[i] for i in range(11) if i in selected];
    print(np.shape(TS_array));
    print(len(xdates));

    f, axarr = plt.subplots(num_rows_plots, num_cols_plots, figsize=(16, 10), dpi=300);
    for i in range(1, len(xdates)):
        rownum, colnum = get_axarr_numbers(num_cols_plots, i);
        data = np.subtract(TS_array[i, :, :], TS_array[i - 1, :, :]);
        axarr[rownum][colnum].imshow(data, aspect=aspect, cmap='rainbow', vmin=vmin, vmax=vmax);
        titlestr = dt.datetime.strftime(xdates[i], "%Y-%m-%d");
        axarr[rownum][colnum].get_xaxis().set_visible(False);
        axarr[rownum][colnum].set_title(titlestr, fontsize=20);

    _ = f.add_axes([0.75, 0.35, 0.2, 0.3], visible=False);
    color_boundary_object = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax);
    custom_cmap = cm.ScalarMappable(norm=color_boundary_object, cmap='rainbow');
    custom_cmap.set_array(np.arange(vmin, vmax));
    cb = plt.colorbar(custom_cmap, aspect=12, fraction=0.2, orientation='vertical');
    cb.set_label('Displacement (mm)', fontsize=18);
    cb.ax.tick_params(labelsize=12);

    plt.savefig(TS_image_file);
    return;
