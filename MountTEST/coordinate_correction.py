from astropy.table import Table
from astropy.time import Time
import numpy as np


class CoordinateCorrection:
    correction = None
    delta_ra = 0
    delta_dec = 0

    def __init__(self):
        pass

    def add_correction(self, ra, dec, delta_ra, delta_dec, jd):
        if self.correction is None:
            self.correction = Table(rows=(ra, dec, delta_ra, delta_dec, jd),
                                    names=['ra', 'dec', 'delta_ra', 'delta_dec', 'jd'])
        else:
            self.correction.add_row((ra, dec, delta_ra, delta_dec, jd))

    def get_correction(self, ra, dec):
        if self.correction is None:
            return 0, 0
        r = np.hypot(self.correction['ra']-ra,
                     self.correction['dec']-dec)
        p = np.where((r < 10./60) &
                     (np.abs(Time.now().jd-self.correction['jd']) < 0.5))[0]
        correction_estimator = self.correction[p]
        self.delta_ra = np.median(correction_estimator['delta_ra'])
        self.delta_dec = np.median(correction_estimator['delta_dec'])
        return self.delta_ra, self.delta_dec
