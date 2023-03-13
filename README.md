
# Introduction

Pyxyfy (*pixie-fi*) is a python package for converting 2D (x,y) point data from multiple cameras into 3D position estimates. The core calibration is built on top of [OpenCV](https://docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html) with additional refinement via bundle adjustment using [SciPy](https://scipy-cookbook.readthedocs.io/items/bundle_adjustment.html). 3D point positions can then be estimated with time synchronized 2D data.

These software calibration tools have long been available, but the process of assembling the calibration images and shepherding data through the various stages of processing is laborious and error prone. Pyxyfy automates that workflow to provide fast, accurate, and consistent camera system calibrations.


This project was inspired by [Anipose](https://www.sciencedirect.com/science/article/pii/S2211124721011797https://www.sciencedirect.com/science/article/pii/S2211124721011797) and seeks to provide similar functionality with improved visual feedback to the user. The calibration process is presented in more granular steps, with a particular emphasis on accurate estimation of camera intrinsics. Because stereocalibration is used to initialize an estimate of relative camera positions, the bundle adjustment process converges quickly to a reasonable optimum.

