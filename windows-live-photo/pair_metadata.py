"""Live Photo pairing helpers. No source photos, recordings, or identifying metadata are included."""
from __future__ import annotations
import struct
import piexif
from PIL import Image
from pillow_heif import register_heif_opener
from pathlib import Path

register_heif_opener()

def mkheic(image:Image.Image,out:Path,identifier:str):
    raw=b'Apple iOS\x00\x00\x01MM\x00\x01\x00\x11\x00\x02\x00\x00\x00\x25\x00\x00\x00\x20\x00\x00\x00\x00'+identifier.encode('ascii')+b'\x00'
    exif=piexif.dump({'Exif':{piexif.ExifIFD.MakerNote:raw}})
    image.convert('RGB').save(out,format='HEIF',quality=95,exif=exif)

def read_boxes(data,start=0,end=None):
    end=len(data) if end is None else end;i=start;result=[]
    while i+8<=end:
        size=int.from_bytes(data[i:i+4],'big');hdr=8
        if size==1:size=int.from_bytes(data[i+8:i+16],'big');hdr=16
        if size==0:size=end-i
        if size<hdr or i+size>end:raise ValueError('Invalid MOV atom')
        result.append((data[i+4:i+8],i,size,hdr));i+=size
    if i!=end:raise ValueError('Invalid MOV layout')
    return result

def child(data,parent,kind):
    _,pos,size,hdr=parent
    return next(x for x in read_boxes(data,pos+hdr,pos+size) if x[0]==kind)

def annotate_mov(src:Path,out:Path,template:bytes,cover_time:float,identifier:str):
    data=bytearray(src.read_bytes());top=read_boxes(data)
    moov=next(x for x in top if x[0]==b'moov')
    if moov[1]+moov[2] != len(data):raise ValueError('MOV moov must be last')
    mvhd=child(data,moov,b'mvhd');mi=mvhd[1];version=data[mi+8]
    if version!=0:raise ValueError('Unsupported movie clock')
    timescale=struct.unpack_from('>I',data,mi+20)[0]
    alltracks=[x for x in read_boxes(data,moov[1]+moov[3],moov[1]+moov[2]) if x[0]==b'trak']
    ids=[]
    for tr in alltracks:
        t=child(data,tr,b'tkhd');p=t[1];ver=data[p+8];ids.append(struct.unpack_from('>I',data,p+(28 if ver else 20))[0])
    new_id=max(ids,default=0)+1
    if moov[1]+8 >= 2**32:raise ValueError('MOV too large')
    track=bytearray(template);root=read_boxes(track)[0]
    tkhd=child(track,root,b'tkhd');edts=child(track,root,b'edts');elst=child(track,edts,b'elst');mdia=child(track,root,b'mdia');mdhd=child(track,mdia,b'mdhd');minf=child(track,mdia,b'minf');stbl=child(track,minf,b'stbl');stco=child(track,stbl,b'stco')
    start_ticks=round(cover_time*timescale);frame_ticks=max(1,round(timescale/30))
    struct.pack_into('>II',track,tkhd[1]+12,0,0);struct.pack_into('>I',track,tkhd[1]+20,new_id);struct.pack_into('>I',track,tkhd[1]+28,start_ticks+frame_ticks)
    struct.pack_into('>I',track,elst[1]+16,start_ticks);struct.pack_into('>I',track,elst[1]+28,frame_ticks)
    struct.pack_into('>II',track,mdhd[1]+12,0,0);struct.pack_into('>I',track,stco[1]+16,moov[1]+8)
    # Update movie's next track ID and append a small, standalone metadata sample before moov.
    struct.pack_into('>I',data,mi+mvhd[2]-4,new_id+1)
    movie=bytearray(data[moov[1]:])
    def atom(name,body): return struct.pack('>I4s',8+len(body),name)+body
    key=b'com.apple.quicktime.content.identifier'
    hdlr=atom(b'hdlr',bytes.fromhex('00000000000000006d6474610000000000000000000000000000'))
    keys=atom(b'keys',b'\x00'*4+struct.pack('>I',1)+atom(b'mdta',key))
    value=atom(b'data',b'\x00\x00\x00\x01'+b'\x00'*4+identifier.encode('ascii'))
    ilst=atom(b'ilst',atom(b'\x00\x00\x00\x01',value))
    meta=atom(b'meta',hdlr+keys+ilst)
    struct.pack_into('>I',movie,0,len(movie)+len(track)+len(meta));movie.extend(track);movie.extend(meta)
    sample=bytes.fromhex('000000090000000100')
    out.write_bytes(data[:moov[1]]+struct.pack('>I4s',8+len(sample),b'mdat')+sample+movie)
