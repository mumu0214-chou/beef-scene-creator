import re
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from engine import make_image, make_video, video_duration, run, ProcessingError, transforms, handheld_sample
from pair_metadata import read_boxes

class ConversionTest(unittest.TestCase):
    def test_batch_formats_and_pairing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            image=root/'source.png'
            Image.new('RGB',(600,800),(180,40,30)).save(image)
            for direction in (True,False,'handheld'):
                heic=root/f'{direction}.HEIC'; movie=root/f'{direction}.MOV'
                make_image(image,heic,movie,.65,.4,direction)
                self.check_pair(heic,movie)
                self.assertAlmostEqual(video_duration(movie),2,delta=.05)
            video=root/'short.mp4'
            run(['-f','lavfi','-i','testsrc=size=480x640:rate=30', '-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','0.8','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',video])
            heic=root/'video.HEIC'; movie=root/'video.MOV'
            actual=make_video(video,heic,movie,0,3)
            self.assertAlmostEqual(actual,.8,delta=.05)
            self.check_pair(heic,movie)
            info=__import__('subprocess').run([__import__('imageio_ffmpeg').get_ffmpeg_exe(),'-hide_banner','-i',str(movie)],capture_output=True).stderr
            self.assertIn(b'Audio:',info)
            with self.assertRaises(ProcessingError):
                make_video(video,root/'bad.HEIC',root/'bad.MOV',.6,2)

    def test_handheld_trajectory(self):
        self.assertAlmostEqual(handheld_sample(0)[0],247)
        self.assertAlmostEqual(handheld_sample(.12)[0],256+.38*__import__('math').sin(6*__import__('math').pi*.12)+.16*__import__('math').sin(10*__import__('math').pi*.12))
        static=transforms(1200,1600,.65,0,'handheld')
        moving=transforms(1200,1600,.65,1,'handheld')
        self.assertEqual(len(moving),60)
        self.assertEqual(static[0],static[30])
        self.assertNotEqual(moving[0],moving[30])
        self.assertAlmostEqual(moving[0][0],moving[0][4])
        self.assertAlmostEqual(moving[0][1],-moving[0][3])

    def check_pair(self,heic,movie):
        with Image.open(heic) as im:
            self.assertEqual(im.width*4,im.height*3)
            maker=im.getexif().get_ifd(0x8769).get(0x927c,b'')
            match=re.search(rb'[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}',maker)
            self.assertIsNotNone(match)
        data=movie.read_bytes()
        self.assertIn(match.group(),data)
        self.assertIn(b'com.apple.quicktime.content.identifier',data)
        self.assertIn(b'com.apple.quicktime.still-image-time',data)
        self.assertTrue(any(b[0]==b'moov' for b in read_boxes(data)))

if __name__=='__main__':unittest.main()
