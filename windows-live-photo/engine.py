from __future__ import annotations
import io, json, math, os, re, subprocess, sys, tempfile, uuid
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageOps
import imageio_ffmpeg
from pair_metadata import annotate_mov, mkheic

HERE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
WIDTH,HEIGHT,FPS=1080,1440,30
FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)

class ProcessingError(Exception): pass

def ffmpeg(): return imageio_ffmpeg.get_ffmpeg_exe()
def run(args, *, input=None):
    p=subprocess.run([ffmpeg(),'-hide_banner','-loglevel','error','-y',*map(str,args)],input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=FLAGS)
    if p.returncode: raise ProcessingError('视频处理失败：'+p.stderr.decode('utf-8','replace')[-1200:])
    return p.stdout

def video_duration(path:Path)->float:
    p=subprocess.run([ffmpeg(),'-hide_banner','-i',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=FLAGS)
    text=p.stderr.decode('utf-8','replace')
    result=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',text)
    if not result or not re.search(r'Stream .*Video:',text): raise ProcessingError('无法读取视频时长或视频画面')
    h,m,s=result.groups(); return int(h)*3600+int(m)*60+float(s)

def grab_frame(path:Path, seconds:float)->Image.Image:
    payload=run(['-ss',f'{seconds:.6f}','-i',path,'-frames:v','1','-f','image2pipe','-vcodec','png','-'])
    if not payload: raise ProcessingError('无法读取视频画面')
    return Image.open(io.BytesIO(payload)).convert('RGB')

def crop_center(im:Image.Image)->Image.Image:
    w,h=im.size; unit=max(1,min(w//3,h//4));cw,ch=unit*3,unit*4
    return im.crop(((w-cw)//2,(h-ch)//2,(w-cw)//2+cw,(h-ch)//2+ch))

def make_video(path:Path,out_photo:Path,out_movie:Path,start:float,duration:float,cover_offset:float|None=None)->float:
    if not all(map(math.isfinite,(start,duration))) or start<0 or not .5<=duration<=3:raise ProcessingError('起点须大于等于 0，时长须在 0.5–3 秒之间')
    total=video_duration(path);remaining=total-start
    if remaining<.5:raise ProcessingError(f'视频总长 {total:.2f} 秒；起点之后不足 0.5 秒，请提前起点')
    actual=min(duration,remaining);cover=actual/2 if cover_offset is None else cover_offset
    if not math.isfinite(cover) or not 0<=cover<actual:raise ProcessingError(f'实际片段为 {actual:.2f} 秒，封面时间须在实际片段内')
    identifier=str(uuid.uuid4()).upper()
    with tempfile.TemporaryDirectory(prefix='live-photo-') as tmp:
        tmp=Path(tmp);intermediate=tmp/'video.mov';cover_image=crop_center(grab_frame(path,start+cover))
        filter_='crop=trunc(min(iw\\,ih*3/4)/2)*2:trunc(min(ih\\,iw*4/3)/2)*2,scale=1080:1440:flags=lanczos,fps=30,setsar=1'
        run(['-ss',f'{start:.6f}','-i',path,'-t',f'{actual:.6f}','-vf',filter_,'-map','0:v:0','-map','0:a:0?','-map_metadata','-1','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',intermediate])
        mkheic(cover_image,out_photo,identifier)
        annotate_mov(intermediate,out_movie,(HERE/'metadata-track.bin').read_bytes(),cover,identifier)
    return actual

@dataclass(frozen=True)
class Point:
    x:float; y:float
    def __add__(self,other):return Point(self.x+other.x,self.y+other.y)
    def __sub__(self,other):return Point(self.x-other.x,self.y-other.y)
    def __mul__(self,n):return Point(self.x*n,self.y*n)

def handheld_sample(t:float):
    # Original two-second handheld trajectory, in the reference image's pixels.
    keys=[(0.00,247,181,45,25),(0.12,256,182,60,-45),(0.28,265,158,0,-100),(0.36,263,153,-25,-10),(0.56,237,121,-120,-80),(0.70,227,133,0,100),(0.85,234,158,70,180),(1.00,247,181,45,25)]
    a,b=next((a,b) for a,b in zip(keys,keys[1:]) if a[0]<=t<b[0])
    dt=b[0]-a[0];u=(t-a[0])/dt
    h00=2*u**3-3*u*u+1;h10=u**3-2*u*u+u;h01=-2*u**3+3*u*u;h11=u**3-u*u
    x=h00*a[1]+h10*dt*a[3]+h01*b[1]+h11*dt*b[3]+.38*math.sin(6*math.pi*t)+.16*math.sin(10*math.pi*t)
    y=h00*a[2]+h10*dt*a[4]+h01*b[2]+h11*dt*b[4]+.25*math.sin(8*math.pi*t+.7)
    angle=math.radians(.08*math.sin(2*math.pi*t+.5)+.045*math.sin(4*math.pi*t))
    return x,y,angle

def transforms(w:int,h:int,crop:float,amp:float,left:bool|str):
    if left=='handheld':
        samples=[handheld_sample(i/60) for i in range(60)]
        cx=(min(x for x,y,a in samples)+max(x for x,y,a in samples))/2
        cy=(min(y for x,y,a in samples)+max(y for x,y,a in samples))/2
        fit=min(w,h*.75)*crop;scale=fit/1080;move_scale=fit/1020;out=[]
        for x,y,angle in samples:
            p=Point(w/2+(x-cx)*move_scale*amp,h/2+(y-cy)*move_scale*amp)
            angle*=amp;a,b=scale*math.cos(angle),-scale*math.sin(angle);d,e=scale*math.sin(angle),scale*math.cos(angle);c=p.x-a*540-b*720;f=p.y-d*540-e*720
            for ox,oy in ((0,0),(1080,0),(0,1440),(1080,1440)):
                sx=a*ox+b*oy+c;sy=d*ox+e*oy+f
                if sx<0 or sy<0 or sx>w or sy>h:raise ProcessingError('运动超出原图边缘，请缩小取景范围或运动幅度')
            out.append((a,b,c,d,e,f))
        return out
    obs=json.loads((HERE/'trajectory.json').read_text(encoding='utf-8'))['result'];t=[q['time']-obs[0]['time'] for q in obs]
    v=[Point(q['x']-obs[0]['x'],(q['y']-obs[0]['y'])*1440/1302) for q in obs]
    def interp(x):
        i=0
        while i<len(t)-2 and t[i+1]<x:i+=1
        a,b=t[i],t[i+1];u=max(0,min(1,(x-a)/(b-a)));m0=(v[i+1]-v[max(i-1,0)])*(1/(t[i+1]-t[max(i-1,0)]));m1=(v[min(i+2,len(t)-1)]-v[i])*(1/(t[min(i+2,len(t)-1)]-t[i]))
        return v[i]*(2*u**3-3*u*u+1)+m0*((u**3-2*u*u+u)*(b-a))+v[i+1]*(-2*u**3+3*u*u)+m1*((u**3-u*u)*(b-a))
    shifts=[interp(i/30) for i in range(60)];mid=Point(w/2,h/2)
    center=Point((min(p.x for p in shifts)+max(p.x for p in shifts))/2,(min(p.y for p in shifts)+max(p.y for p in shifts))/2)
    scale=min(w,h*.75)*crop/1080;start=interp(.5);direction=-1 if left else 1; result=[]
    for i,shift in enumerate(shifts):
        tm=i/30;angle=0
        if tm<=.5:p=mid-(shift-center)*(scale*amp)
        else:
            u=min(1,(tm-.5)/(59/30-.5));q=3*u*u-2*u*u*u;angle=(1 if left else -1)*5*math.pi/180*q*amp
            wob=Point(w/1086*math.sin(2*math.pi*2.7*(tm-.5)),w/1086*.8*math.sin(2*math.pi*2.2*(tm-.5)))
            anchor=mid-(start-center)*(scale*amp)
            p=anchor+(Point(direction*w/1086*18*q,direction*w/1086*25*q)+wob)*amp-(shift-start)*(scale*.20*amp)
        a,b=scale*math.cos(angle),-scale*math.sin(angle);d,e=scale*math.sin(angle),scale*math.cos(angle);c=p.x-a*540-b*720;f=p.y-d*540-e*720
        for x,y in ((0,0),(1080,0),(0,1440),(1080,1440)):
            sx=a*x+b*y+c;sy=d*x+e*y+f
            if sx<0 or sy<0 or sx>w or sy>h:raise ProcessingError('运动超出原图边缘，请缩小取景范围或运动幅度')
        result.append((a,b,c,d,e,f))
    return result

def make_image(path:Path,out_photo:Path,out_movie:Path,crop:float,amp:float,left:bool):
    if not .45<=crop<=.95 or not 0<=amp<=1.5:raise ProcessingError('取景范围或运动幅度无效')
    im=ImageOps.exif_transpose(Image.open(path)).convert('RGB');w,h=im.size;mats=transforms(w,h,crop,amp,left);unit=max(1,round(min(w,h*.75)*crop/3));cw,ch=unit*3,unit*4
    a,b,c,d,e,f=mats[30];cover=im.transform((cw,ch),Image.Transform.AFFINE,(a*1080/cw,b*1440/ch,c,d*1080/cw,e*1440/ch,f),resample=Image.Resampling.BICUBIC)
    identifier=str(uuid.uuid4()).upper()
    with tempfile.TemporaryDirectory(prefix='live-photo-') as tmp:
        intermediate=Path(tmp)/'video.mov';cmd=[ffmpeg(),'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1440','-r','30','-i','-','-map_metadata','-1','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p',str(intermediate)]
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=FLAGS)
        try:
            for mat in mats:
                frame=im.transform((WIDTH,HEIGHT),Image.Transform.AFFINE,mat,resample=Image.Resampling.BICUBIC);proc.stdin.write(frame.tobytes())
            proc.stdin.close();error=proc.stderr.read();code=proc.wait()
            if code:raise ProcessingError('视频编码失败：'+error.decode('utf-8','replace')[-1000:])
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
            if proc.stderr:proc.stderr.close()
        mkheic(cover,out_photo,identifier)
        annotate_mov(intermediate,out_movie,(HERE/'metadata-track.bin').read_bytes(),1.0,identifier)
