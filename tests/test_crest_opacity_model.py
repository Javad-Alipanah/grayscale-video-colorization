"""Synthetic preservation test; private lecture-native image fixtures excluded."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
import unittest
import numpy as np
from crest_opacity_model import SourceCrestOpacity

class SourceCrestTest(unittest.TestCase):
    def setUp(self):
        self.model=SourceCrestOpacity.__new__(SourceCrestOpacity)
        self.model.mask=np.zeros((8,8),bool);self.model.mask[2:6,2:6]=True
        self.model.core=self.model.mask.copy();self.model.peak=np.full((8,8),100,np.float32)
        self.model.local_white=np.full((8,8),200,np.float32)
        self.model.plate=lambda frame,current:(np.full((8,8),100,np.float32),[])
        self.source=np.full((3,8,8),128,np.uint8);self.source[0]=150
        self.baseline=self.source.copy();self.baseline[1]=110;self.baseline[2]=150
    def test_exact_y_outside_support_and_opacity(self):
        after,alpha,proof=self.model.apply(79325,self.source,self.baseline)
        np.testing.assert_array_equal(after[0],self.source[0])
        np.testing.assert_array_equal(after[1:,~self.model.mask],self.baseline[1:,~self.model.mask])
        self.assertEqual(float(alpha.max()),.5)
        self.assertEqual(int(after[1,3,3]),119);self.assertEqual(int(after[2,3,3]),139)
        self.assertEqual(proof['strength'],.5)
    def test_endpoints_unchanged_and_y_mismatch_rejected(self):
        for frame in [79297,79525]:
            after,alpha,_=self.model.apply(frame,self.source,self.baseline)
            np.testing.assert_array_equal(after,self.baseline);self.assertFalse(alpha.any())
        self.baseline[0,0,0]=99
        with self.assertRaises(ValueError):self.model.apply(79325,self.source,self.baseline)

if __name__=='__main__':unittest.main()
