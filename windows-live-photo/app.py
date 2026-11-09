from __future__ import annotations
import os,queue,subprocess,sys,threading,traceback,uuid
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image,ImageDraw,ImageOps,ImageTk
from pillow_heif import register_heif_opener
from engine import make_image,make_video,video_duration,grab_frame,crop_center,transforms,ProcessingError

register_heif_opener()
PHOTO_EXT={'.jpg','.jpeg','.png','.webp','.heic','.heif','.bmp','.tif','.tiff'}
VIDEO_EXT={'.mov','.mp4','.m4v','.mkv','.avi','.webm'}

class Panel(ttk.Frame):
    def __init__(self,parent,root,kind):
        super().__init__(parent,padding=18);self.root=root;self.kind=kind;self.items=[];self.selected=None;self.outdir='';self.busy=False;self.q=queue.Queue();self.preview_generation=0
        self.start=tk.StringVar(value='0');self.duration=tk.StringVar(value='2');self.middle=tk.BooleanVar(value=True);self.cover=tk.StringVar(value='1');self.crop=tk.DoubleVar(value=.54);self.amplitude=tk.DoubleVar(value=1);self.direction=tk.StringVar(value='左旋转');self.crop_label=tk.StringVar();self.amp_label=tk.StringVar();self.info=tk.StringVar(value='请添加素材并选择输出位置');self.batch_path=None
        self.columnconfigure(0,weight=1);self.columnconfigure(1,weight=1);self.rowconfigure(0,weight=1)
        left=ttk.Frame(self);left.grid(row=0,column=0,sticky='nsew',padx=(0,20));left.columnconfigure(0,weight=1)
        right=ttk.Frame(self);right.grid(row=0,column=1,sticky='nsew');right.columnconfigure(0,weight=1);right.rowconfigure(1,weight=1)
        ttk.Label(left,text='批量图片转实况图' if kind=='image' else '批量视频转实况图',font=('Microsoft YaHei UI',17,'bold')).grid(row=0,column=0,sticky='w',pady=(0,10))
        controls=ttk.Frame(left);controls.grid(row=1,column=0,sticky='ew');self.add_btn=ttk.Button(controls,text='添加图片…' if kind=='image' else '添加视频…',command=self.choose);self.add_btn.pack(side='left');self.folder_btn=ttk.Button(controls,text='添加文件夹…',command=self.choose_folder);self.folder_btn.pack(side='left',padx=6);self.clear_btn=ttk.Button(controls,text='清空',command=self.clear);self.clear_btn.pack(side='right')
        self.drop=tk.Label(left,text='将图片或文件夹拖到这里，可一次添加多个' if kind=='image' else '将视频或文件夹拖到这里，可一次添加多个',height=3,relief='groove',bg='#f3f6f5',fg='#3f4a47');self.drop.grid(row=2,column=0,sticky='ew',pady=9);self.drop.drop_target_register(DND_FILES);self.drop.dnd_bind('<<Drop>>',self.drop_files)
        title=ttk.Frame(left);title.grid(row=3,column=0,sticky='ew');self.count_label=ttk.Label(title,text='素材列表 · 0 个',font=('Microsoft YaHei UI',10,'bold'));self.count_label.pack(side='left');ttk.Button(title,text='移除选中项',command=self.remove).pack(side='right')
        listframe=ttk.Frame(left);listframe.grid(row=4,column=0,sticky='ew',pady=5);listframe.columnconfigure(0,weight=1)
        self.filelist=tk.Listbox(listframe,height=5,exportselection=False);self.filelist.grid(row=0,column=0,sticky='ew');self.filelist.bind('<<ListboxSelect>>',self.on_select);scroll=ttk.Scrollbar(listframe,orient='vertical',command=self.filelist.yview);scroll.grid(row=0,column=1,sticky='ns');self.filelist.configure(yscrollcommand=scroll.set)
        out=ttk.Frame(left);out.grid(row=5,column=0,sticky='ew',pady=5);self.out_btn=ttk.Button(out,text='选择输出位置…',command=self.choose_output);self.out_btn.pack(side='left');self.outlabel=ttk.Label(out,text='未选择');self.outlabel.pack(side='left',padx=6,fill='x',expand=True)
        self.opts=ttk.Frame(left);self.opts.grid(row=6,column=0,sticky='ew',pady=3);self.opts.columnconfigure(1,weight=1)
        if kind=='image':
            ttk.Label(self.opts,text='运动轨迹').grid(row=0,column=0,sticky='w');f=ttk.Frame(self.opts);f.grid(row=0,column=1,sticky='w');ttk.Radiobutton(f,text='单向左旋转',value='左旋转',variable=self.direction).pack(side='left');ttk.Radiobutton(f,text='单向右旋转',value='右旋转',variable=self.direction).pack(side='left')
            ttk.Label(self.opts,textvariable=self.crop_label).grid(row=1,column=0,columnspan=2,sticky='w',pady=(7,0));ttk.Scale(self.opts,from_=.45,to=.95,variable=self.crop,command=self.scale_changed).grid(row=2,column=0,columnspan=2,sticky='ew')
            ttk.Label(self.opts,textvariable=self.amp_label).grid(row=3,column=0,columnspan=2,sticky='w',pady=(7,0));ttk.Scale(self.opts,from_=0,to=1.5,variable=self.amplitude,command=self.scale_changed).grid(row=4,column=0,columnspan=2,sticky='ew');self.scale_changed()
            hint='红框为中央静止取景；幅度过大、画面越界时需要调小。'
        else:
            ttk.Label(self.opts,text='片段起点（秒）').grid(row=0,column=0,sticky='w');ttk.Entry(self.opts,textvariable=self.start,width=8).grid(row=0,column=1,sticky='w');ttk.Button(self.opts,text='预览起点',command=lambda:self.request_preview('start')).grid(row=0,column=2)
            ttk.Label(self.opts,text='片段时长（秒）').grid(row=1,column=0,sticky='w',pady=5);ttk.Entry(self.opts,textvariable=self.duration,width=8).grid(row=1,column=1,sticky='w');ttk.Label(self.opts,text='0.5–3 秒').grid(row=1,column=2)
            ttk.Checkbutton(self.opts,text='封面使用片段中间帧',variable=self.middle,command=self.toggle_cover).grid(row=2,column=0,columnspan=2,sticky='w');ttk.Button(self.opts,text='预览封面',command=lambda:self.request_preview('cover')).grid(row=2,column=2)
            self.cover_lbl=ttk.Label(self.opts,text='封面时间（片段内秒）');self.cover_entry=ttk.Entry(self.opts,textvariable=self.cover,width=8)
            self.video_hint=ttk.Label(self.opts,text='',wraplength=430,foreground='#596563');self.video_hint.grid(row=4,column=0,columnspan=3,sticky='w',pady=4)
            for v in (self.start,self.duration):v.trace_add('write',lambda *_:self.update_video_hint())
            hint='批量使用相同的片段设置；过短时自动取剩余部分。输出居中裁为 3:4，保留原声。'
        ttk.Label(left,text=hint,foreground='#596563',wraplength=450).grid(row=7,column=0,sticky='w',pady=7)
        self.progress=ttk.Progressbar(left,maximum=100);self.progress.grid(row=8,column=0,sticky='ew',pady=4)
        self.status=tk.Text(left,height=4,wrap='word',font=('Microsoft YaHei UI',9),state='disabled',relief='flat',bg=self.root.cget('bg'));self.status.grid(row=9,column=0,sticky='ew');self.log('等待素材。')
        bottom=ttk.Frame(left);bottom.grid(row=10,column=0,sticky='ew',pady=8);self.start_btn=ttk.Button(bottom,text='开始批量制作',command=self.start_batch);self.start_btn.pack(side='left');self.open_btn=ttk.Button(bottom,text='打开结果文件夹',command=self.open_results);self.open_btn.pack(side='left',padx=8);self.open_btn.state(['disabled'])
        self.preview_title=ttk.Label(right,text='取景预览' if kind=='image' else '视频画面预览',font=('Microsoft YaHei UI',12,'bold'));self.preview_title.grid(row=0,column=0,sticky='w')
        self.canvas=tk.Canvas(right,bg='#eff1ef',width=440,height=600,highlightthickness=0);self.canvas.grid(row=1,column=0,sticky='nsew',pady=8);self.canvas.bind('<Configure>',lambda _:self.request_preview('current'))
        ttk.Label(right,text='图片显示原图和取景框。' if kind=='image' else '显示所选视频的起点或封面画面；输出按中央 3:4 裁切。',foreground='#596563',wraplength=440).grid(row=2,column=0,sticky='w')
        self.update_queue()
    def log(self,text):
        self.status.configure(state='normal');self.status.delete('1.0','end');self.status.insert('1.0',text);self.status.configure(state='disabled')
    def toggle_cover(self):
        if self.middle.get():self.cover_lbl.grid_remove();self.cover_entry.grid_remove()
        else:self.cover_lbl.grid(row=3,column=0,sticky='w');self.cover_entry.grid(row=3,column=1,sticky='w')
    def scale_changed(self,*_):
        self.crop_label.set(f'取景范围：{round(self.crop.get()*100)}%（输出 3:4）');self.amp_label.set(f'运动幅度：{round(self.amplitude.get()*100)}%')
        self.root.after_cancel(self.pending) if hasattr(self,'pending') else None
        self.pending=self.root.after(150,lambda:self.request_preview('current'))
    def supported(self,p):return p.suffix.lower() in (PHOTO_EXT if self.kind=='image' else VIDEO_EXT)
    def add(self,paths):
        if self.busy:return
        found=[]
        for p in paths:
            try:
                p=Path(p)
                if p.is_dir():found.extend(q for q in p.rglob('*') if q.is_file() and self.supported(q))
                elif p.is_file() and self.supported(p):found.append(p)
            except OSError:continue
        existing={os.path.normcase(str(p.resolve())) for p in self.items};added=0
        for p in sorted(found,key=lambda x:str(x).casefold()):
            k=os.path.normcase(str(p.resolve()))
            if k not in existing:self.items.append(p.resolve());existing.add(k);self.filelist.insert('end',p.name);added+=1
        self.count_label.configure(text=f'素材列表 · {len(self.items)} 个');self.log(f'已添加 {added} 个素材，共 {len(self.items)} 个')
        if self.selected is None and self.items:self.filelist.selection_set(0);self.on_select()
    def drop_files(self,event):self.add(self.root.tk.splitlist(event.data));return event.action
    def choose(self):
        types=[('图片','*.jpg *.jpeg *.png *.webp *.heic *.heif *.bmp *.tif *.tiff'),('所有文件','*.*')] if self.kind=='image' else [('视频','*.mov *.mp4 *.m4v *.mkv *.avi *.webm'),('所有文件','*.*')]
        self.add(filedialog.askopenfilenames(title='选择素材',filetypes=types))
    def choose_folder(self):
        p=filedialog.askdirectory(title='选择素材文件夹')
        if p:self.add([p])
    def choose_output(self):
        p=filedialog.askdirectory(title='选择输出位置')
        if p:self.outdir=p;self.outlabel.configure(text=p)
    def clear(self):
        if self.busy:return
        self.items.clear();self.selected=None;self.filelist.delete(0,'end');self.count_label.configure(text='素材列表 · 0 个');self.canvas.delete('all');self.log('已清空素材列表。')
        if self.kind=='video':self.video_hint.configure(text='选择视频后显示可用时长。')
    def remove(self):
        if self.busy:return
        indices=list(self.filelist.curselection())
        for i in reversed(indices):self.items.pop(i);self.filelist.delete(i)
        self.selected=None
        if self.items:self.filelist.selection_set(min(indices[0],len(self.items)-1) if indices else 0);self.on_select()
        else:self.canvas.delete('all')
        self.count_label.configure(text=f'素材列表 · {len(self.items)} 个')
    def on_select(self,event=None):
        sel=self.filelist.curselection()
        if not sel:return
        self.selected=self.items[sel[0]];self.preview_title.configure(text=('取景预览 · ' if self.kind=='image' else '视频预览 · ')+self.selected.name)
        if self.kind=='video':self.update_video_hint()
        self.request_preview('current')
    def values(self):
        try:return float(self.start.get()),float(self.duration.get()),None if self.middle.get() else float(self.cover.get())
        except ValueError:raise ProcessingError('请输入有效的数字')
    def update_video_hint(self):
        if self.kind!='video' or not self.selected:return
        try:
            start,duration,_=self.values();total=video_duration(self.selected);remaining=max(0,total-start)
            t=f'视频总长 {total:.2f} 秒；'+(f'将自动缩短为 {remaining:.2f} 秒' if remaining<duration else f'将截取 {duration:.2f} 秒')
            self.video_hint.configure(text=t)
        except Exception:self.video_hint.configure(text='请输入有效的时间')
    def request_preview(self,mode):
        if not self.selected:return
        self.preview_generation+=1;gen=self.preview_generation;p=self.selected;kind=self.kind;crop=self.crop.get();w=max(100,self.canvas.winfo_width());h=max(100,self.canvas.winfo_height())
        try:
            if kind=='video':
                start,duration,cover=self.values();actual=min(duration,max(0,video_duration(p)-start));offset=actual/2 if cover is None else cover
                if actual<.5 or start<0 or not 0<=offset<actual:raise ProcessingError('请检查视频起点、时长和封面时间')
                at=start+(0 if mode=='start' else offset)
            else:at=0
        except Exception as e:self.log(str(e));return
        def work():
            try:
                if kind=='video':im=crop_center(grab_frame(p,at))
                else:im=ImageOps.exif_transpose(Image.open(p)).convert('RGB')
                original=im.size;im.thumbnail((max(50,w-20),max(50,h-20)),Image.Resampling.LANCZOS)
                if kind=='image':
                    draw=ImageDraw.Draw(im);cw=min(im.width,im.height*.75)*crop;ch=cw/.75;cx,cy=im.width/2,im.height/2;draw.rectangle((cx-cw/2,cy-ch/2,cx+cw/2,cy+ch/2),outline='#ff4b40',width=3)
                self.q.put(('preview',gen,im,original))
            except Exception as e:self.q.put(('preview_error',gen,str(e)))
        threading.Thread(target=work,daemon=True).start()
    def update_queue(self):
        try:
            while True:
                msg=self.q.get_nowait();kind=msg[0]
                if kind=='preview' and msg[1]==self.preview_generation:
                    self.tkimage=ImageTk.PhotoImage(msg[2]);self.canvas.delete('all');self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.tkimage)
                elif kind=='preview_error' and msg[1]==self.preview_generation:self.log(msg[2])
                elif kind=='progress':self.progress['value']=msg[1];self.log(msg[2])
                elif kind=='done':
                    self.busy=False;self.set_busy(False);self.progress['value']=100;self.batch_path=msg[1];self.open_btn.state(['!disabled']);self.log(msg[2])
                elif kind=='error':self.busy=False;self.set_busy(False);self.log(msg[1])
        except queue.Empty:pass
        self.root.after(100,self.update_queue)
    def set_busy(self,busy):
        for widget in (self.add_btn,self.folder_btn,self.clear_btn,self.out_btn,self.start_btn):widget.state(['disabled'] if busy else ['!disabled'])
    def open_results(self):
        if self.batch_path:
            if sys.platform=='win32':os.startfile(self.batch_path)
            elif sys.platform=='darwin':subprocess.Popen(['open',self.batch_path])
    def start_batch(self):
        if self.busy:return
        if not self.items or not self.outdir:messagebox.showinfo('提示','请添加素材并选择输出位置。');return
        try:
            if self.kind=='image':
                crop,amp=self.crop.get(),self.amplitude.get();left=self.direction.get()=='左旋转';settings=(crop,amp,left)
            else:
                start,duration,cover=self.values()
                if start<0 or not .5<=duration<=3 or (cover is not None and not 0<=cover<duration):raise ProcessingError('请检查起点、时长和封面时间')
                settings=(start,duration,cover)
        except Exception as e:messagebox.showerror('设置无效',str(e));return
        items=list(self.items);outdir=Path(self.outdir);kind=self.kind;self.busy=True;self.set_busy(True);self.open_btn.state(['disabled']);self.progress['value']=0
        def worker():
            try:
                batch=outdir/('实况图-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:4]);batch.mkdir()
                errors=[];short=[]
                for i,p in enumerate(items):
                    self.q.put(('progress',100*i/len(items),f'正在制作 {i+1}/{len(items)}：{p.name}'))
                    name=f'{i+1:03d}_{p.stem}';photo=batch/(name+'.HEIC');movie=batch/(name+'.MOV')
                    try:
                        if kind=='image':make_image(p,photo,movie,*settings)
                        else:
                            actual=make_video(p,photo,movie,*settings)
                            if actual<settings[1]-.01:short.append(f'{p.name}：{actual:.2f} 秒')
                    except Exception as e:
                        photo.unlink(missing_ok=True);movie.unlink(missing_ok=True);errors.append(f'{p.name}：{e}')
                lines=[f'完成 {len(items)-len(errors)}/{len(items)} 组配对文件']
                if short:lines.append('自动缩短：'+'；'.join(short))
                if errors:lines.append('未完成：'+'；'.join(errors))
                self.q.put(('done',str(batch),'\n'.join(lines)))
            except Exception as e:self.q.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__();self.title('实况图制作器 Windows 版');self.geometry('1100x800');self.minsize(920,700)
        notebook=ttk.Notebook(self);notebook.pack(fill='both',expand=True);notebook.add(Panel(notebook,self,'image'),text='图片转实况');notebook.add(Panel(notebook,self,'video'),text='视频转实况')

if __name__=='__main__':
    app=App()
    if '--self-test' in sys.argv:app.after(500,app.destroy)
    app.mainloop()
