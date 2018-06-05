# -*- coding: utf-8 -*-
"""
New interface for the photobooth

@author: Laurent Alacoque 2o18
"""

from Tkinter import *
import tkMessageBox
from PIL import ImageTk,Image
from tkkb import Tkkb
from tkImageLabel import ImageLabel
from constants import *
import custom as custom
import time
import traceback
import mailfile

import os
from credentials import OAuth2Login
import config as google_credentials

try:
    import hardware_buttons as HWB
except ImportError:
    print "Error importing hardware_buttons, using fakehardware instead"
    print traceback.print_exc()
    import fakehardware as HWB
    
try:
    import picamera as mycamera
    from picamera.color import Color
except ImportError:
    print "picamera not found, trying cv2_camera"
    try:
        import cv2_camera as mycamera
    except ImportError:
        print "cv2_camera import failed : using fake hardware instead"
        import fakehardware as mycamera
        from fakehardware import Color

CONFIG_BUTTON_IMG = "ressources/ic_settings.png"
EMAIL_BUTTON_IMG = "ressources/ic_email.png"
HARDWARE_POLL_PERIOD = 100


class UserInterface():
    def __init__(self, window_size=None, poll_period=HARDWARE_POLL_PERIOD, config=custom):
        self.root = Tk()
        self.root.configure(background='black')
        self.config=config
        if window_size is not None:
            self.size=window_size
        else:
            self.size=(640,480)
        
        self.root.geometry('%dx%d+0+0'%(self.size[0],self.size[1]))

        #Configure Image holder
        self.image = ImageLabel(self.root, size=self.size)
        self.image.place(x=0, y=0, relwidth = 1, relheight=1)
        self.image.configure(background='black')

        #Create config button
        cfg_image = Image.open(CONFIG_BUTTON_IMG)
        w,h = cfg_image.size
        self.cfg_imagetk = ImageTk.PhotoImage(cfg_image)
        self.cfg_btn   = Button(self.root, image=self.cfg_imagetk, height=h, width=w, command=self.launch_config)
        self.cfg_btn.place(x=0, y=0)
        self.cfg_btn.configure(background = 'black')        
        
        #Create sendmail Button
        mail_image = Image.open(EMAIL_BUTTON_IMG)
        w,h = mail_image.size
        self.mail_imagetk = ImageTk.PhotoImage(mail_image)
        self.mail_btn  = Button(self.root,image = self.mail_imagetk, height=h, width=w, command=self.send_email )
        self.mail_btn.place(x=SCREEN_W-w-2, y=0)
        self.mail_btn.configure(background = 'black')
        
        #Create status line
        self.status_lbl = Label(self.root, text="", font=("Helvetica", 20))
        self.status_lbl.config(background='black', foreground='white')
        self.status_lbl.place(x=self.cfg_btn['width'], y=0)
        
        #State variables
        self.signed_in = False
        self.auth_after_id = None
        self.poll_period = poll_period
        self.poll_after_id = None
        
        self.last_picture_filename = None
        self.last_picture_time = time.time()
        self.last_picture_mime_type = None
        
        self.tkkb = None
        self.email_addr = StringVar()
        
        self.suspend_poll = False
        
        #Google credentials
        self.credentials = google_credentials.Credential()
        self.configdir = os.path.expanduser('./')
        self.client_secrets = os.path.join(self.configdir, 'OpenSelfie.json')
        self.credential_store = os.path.join(self.configdir, 'credentials.dat')
        self.client = None
        
        #Hardware buttons
        self.buttons = HWB.Buttons()
        
        #Camera
        self.camera = mycamera.PiCamera()
        self.camera.annotate_text_size = 160 # Maximum size
        self.camera.annotate_foreground = Color('white')
        self.camera.annotate_background = Color('black')
        
    
    def __del__(self):
        try:
            self.root.after_cancel(self.auth_after_id)
            self.root.after_cancel(self.poll_after_id)
            self.camera.close()
        except:
            pass
        
    def status(self, status_text):
        self.status_lbl['text'] = status_text
    
    def start_ui(self):
        self.auth_after_id = self.root.after(100, self.refresh_auth)
        self.poll_after_id = self.root.after(self.poll_period, self.run_periodically)
        print "Done"
        self.root.mainloop()

    def launch_config(self):
        self.config.customize(self.root)
        
    def run_periodically(self):
        if not self.suspend_poll == True:
            self.status('')
            btn_state = self.buttons.state()
            if btn_state == 1:
                self.snap("None")
            elif btn_state == 2:
                self.snap("Four")
            elif btn_state == 3:
                self.snap("Animation")
        self.poll_after_id = self.root.after(self.poll_period, self.run_periodically)

    def snap(self,mode="None"):
        print "snap (mode=%s)" % mode
        self.suspend_poll = True
        # clear status
        self.status("")
        
        if mode not in EFFECTS_PARAMETERS.keys():
            print "Wrong mode %s defaults to 'None'" % mode
            mode = "None"
        
        #hide backgroud image
        self.image.unload()

        # update this to be able to send email and upload
        # snap_filename = snap_picture(mode)
        # take a snapshot here
        snap_filename = None
        snap_size = EFFECTS_PARAMETERS[mode]['snap_size']
        try:
            # 1. Start Preview
            self.camera.resolution = snap_size
            self.camera.start_preview()
            # 2. Show initial countdown
            self.__show_countdown(custom.countdown1)
            # 3. Take snaps and combine them
            if mode == 'None':
                # simple shot with logo
                self.camera.capture('snapshot.jpg')
                self.camera.stop_preview()
            
                snapshot = Image.open('snapshot.jpg')
                if custom.logo is not None :
                    size = snapshot.size
                    #resize logo to the wanted size
                    custom.logo.thumbnail((EFFECTS_PARAMETERS['None']['logo_size'],EFFECTS_PARAMETERS['None']['logo_size'])) 
                    logo_size = custom.logo.size
                    #put logo on bottom right with padding
                    yoff = size[1] - logo_size[1] - EFFECTS_PARAMETERS['None']['logo_padding']
                    xoff = size[0] - logo_size[0] - EFFECTS_PARAMETERS['None']['logo_padding']
                    snapshot.paste(custom.logo,(xoff, yoff), custom.logo)
                snapshot.save('snapshot.jpg')
                snap_filename = 'snapshot.jpg'
                self.last_picture_mime_type = 'image/jpg'
                
            elif mode == 'Four':
                # collage of four shots
                # compute collage size
                w = snap_size[0]
                h = snap_size[1]
                w_ = w * 2
                h_ = h * 2
                # take 4 photos and merge into one image.
                self.camera.capture('collage_1.jpg')
                self.__show_countdown(custom.countdown2)
                self.camera.capture('collage_2.jpg')
                self.__show_countdown(custom.countdown2)
                self.camera.capture('collage_3.jpg')
                self.__show_countdown(custom.countdown2)
                self.camera.capture('collage_4.jpg')
                # Assemble collage
                self.camera.stop_preview()
                self.status("Assembling collage")
                snapshot = Image.new('RGBA', (w_, h_))
                snapshot.paste(Image.open('collage_1.jpg'), (  0,   0,  w, h))
                snapshot.paste(Image.open('collage_2.jpg'), (w,   0, w_, h))
                snapshot.paste(Image.open('collage_3.jpg'), (  0, h,  w, h_))
                snapshot.paste(Image.open('collage_4.jpg'), (w, h, w_, h_))
                #paste the collage enveloppe if it exists
                try:
                    front = Image.open(EFFECTS_PARAMETERS[mode]['foreground_image'])
                    front = front.resize((w_,h_))
                    front = front.convert('RGBA')
                    snapshot = snapshot.convert('RGBA')
                    #print snapshot
                    #print front
                    snapshot=Image.alpha_composite(snapshot,front)

                except Exception, e:
                    traceback.print_exc()

                self.status("")
                snapshot = snapshot.convert('RGB')
                snapshot.save('collage.jpg')
                snap_filename = 'collage.jpg'
                self.last_picture_mime_type = 'image/jpg'
                
            elif mode == 'Animation':
                # animated gifs
                # below is taken from official PiCamera doc and adapted
                # take GIF_FRAME_NUMBER pictures resize to GIF_SIZE
                for i, filename in enumerate(self.camera.capture_continuous('animframe-{counter:03d}.jpg')):
                    # print(filename)
                    # TODO : enqueue the filenames and use that in the command line
                    time.sleep(EFFECTS_PARAMETERS[mode]['snap_period_millis'] / 1000.0)
                    # preload first frame because convert can be slow
                    if i == 0: self.image.load(filename)
                    if i >= EFFECTS_PARAMETERS[mode]['frame_number']:
                        break
                self.camera.stop_preview()
                
                # Assemble images using image magick
                self.status("Assembling animation")
                command_string = "convert -delay " + str(EFFECTS_PARAMETERS[mode]['gif_period_millis']) + " animframe-*.jpg animation.gif"
                os.system(command_string)
                self.status("")
                snap_filename = 'animation.gif'
                self.last_picture_mime_type = 'image/gif'
            
            # Here, the photo or animation is in snap_filename
            if os.path.exists(snap_filename):
                self.last_picture_filename = snap_filename
                self.last_picture_time = time.time()
                self.last_picture_timestamp = time.strftime("%Y-%m-%d_%H-%M-%S",time.gmtime())
                self.last_picture_title = time.strftime("%d/%m/%Y %H:%M:%S",time.gmtime()) #TODO add event name
                
                # 1. Display
                self.image.load(snap_filename)
                # 2. Archive
                if custom.ARCHIVE:
                    if os.path.exists(custom.archive_dir):
                        new_filename = ""
                        if mode == 'None':
                            new_filename = "snapshot-%s.jpg" % self.last_picture_timestamp
                        elif mode == 'Four':
                            new_filename = "collage-%s.jpg" % self.last_picture_timestamp
                        elif mode == 'Animation':
                            new_filename = "animation-%s.gif" % self.last_picture_timestamp
                            
                        new_filename = os.path.join(custom.archive_dir,new_filename)
                        command = (['mv', self.last_picture_filename, new_filename])
                        call(command)
                    else:
                        print "Error : archive_dir %s doesn't exist"% custom.archive_dir

                # 3. Upload
                if self.signed_in:
                    self.status("Uploading image")
                    self.googleUpload(
                        self.last_picture_filename, 
                        title= self.last_picture_title,
                        caption = custom.photoCaption + " " + self.last_picture_title,
                        mime_type = self.last_picture_mime_type)
                    self.status("")
            else:
                # error
                self.status("Snap failed :(")
                self.image.unload()
        except Exception, e:
            print e
            traceback.print_exc()
            snapshot = None
        self.suspend_poll = False    
        return snap_filename

    def __countdown_set_led(self,state):
        ''' if you have a hardware led on the camera, link it to this'''
        try:
            self.camera.led = state
        except:
            pass
            
    def __show_countdown(self,countdown):
        ''' display countdown. the camera should have a preview active and the resolution must be set'''
        led_state = False
        self.__countdown_set_led(led_state)

        self.camera.annotate_text = "" # Remove annotation
        #self.camera.preview.window = (0, 0, SCREEN_W, SCREEN_H)
        self.camera.preview.fullscreen = True

        #Change text every second and blink led
        for i in range(countdown):
            # Annotation text
            self.camera.annotate_text = "  " + str(countdown - i) + "  "
            if i < countdown - 2:
            # slow blink until -2s
                time.sleep(1)
                led_state = not led_state
                self.__countdown_set_led(led_state)
            else:
            # fast blink until the end
                for j in range(5):
                    time.sleep(.2)
                    led_state = not led_state
                    self.__countdown_set_led(led_state)
        self.camera.annotate_text = ""

    def refresh_auth(self):
        if self.__google_auth():
            self.mail_btn.configure(state=NORMAL)
            self.signed_in = True
        else:
            self.mail_btn.configure(state=DISABLED)
            self.signed_in = False
            print 'refresh failed'

        #relaunch periodically
        self.auth_after_id = self.root.after(self.config.oauth2_refresh_period, self.refresh_auth)
        
    def __google_auth(self):
        # Connection to Google for Photo album upload
        try:
            # Create a client class which will make HTTP requests with Google Docs server.
            self.client = OAuth2Login(self.client_secrets, self.credential_store, self.credentials.key)
            return True
        except Exception, e:
            print 'could not login to Google, check .credential file\n   %s' % e
            return False
            
    def googleUpload(self,filen, title='Photobooth photo', caption = None, mime_type='image/jpeg'):
        #upload to picasa album
        if caption  is None:
            caption = custom.photoCaption
        if custom.albumID != 'None':
            album_url ='/data/feed/api/user/%s/albumid/%s' % (self.credentials.key, custom.albumID)
            photo = self.client.InsertPhotoSimple(album_url, title, caption, filen ,content_type=mime_type)
        else:
            raise ValueError("albumID not set")    
            
    def send_email(self):
        self.suspend_poll = True
        if self.signed_in and self.tkkb is None:
            self.email_addr.set("")
            self.tkkb = Toplevel(self.root)
            def onEnter(*args):
                self.kill_tkkb()
                self.__send_picture()
            Tkkb(self.tkkb, self.email_addr, onEnter=onEnter)
            self.tkkb.wm_attributes("-topmost", 1)
            self.tkkb.transient(self.root)
            self.tkkb.protocol("WM_DELETE_WINDOW", self.kill_tkkb)
            
    def kill_tkkb(self):
        if self.tkkb is not None:
            self.tkkb.destroy()
            self.tkkb = None
            self.suspend_poll = False
            
    def __send_picture(self):
        if self.signed_in:
            print 'sending photo by email to %s' % self.email_addr.get()
            self.status("Sending Email")
            try:
                mailfile.sendMail(self.email_addr.get().strip(),
                         custom.emailSubject,
                         custom.emailMsg,
                         self.last_picture_filename)
                self.kill_tkkb()
            except Exception, e:
                print 'Send Failed ::', e
                self.status("Send failed :(")
            self.status("")
        else:
            print 'Not signed in'

if __name__ == '__main__':
    ui = UserInterface(window_size=(SCREEN_W, SCREEN_H))
    ui.start_ui()



