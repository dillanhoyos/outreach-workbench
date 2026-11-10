#!/usr/bin/env python3
"""Install one reader entry without replacing other crontab jobs (UTC host required)."""
import argparse,os,shlex,subprocess
from pathlib import Path
from datetime import datetime,timezone

START='# BEGIN OUTREACH WORKBENCH READER'
END='# END OUTREACH WORKBENCH READER'
def updated_crontab(old,repo,remove=False):
    if old.count(START)!=old.count(END) or old.count(START)>1:raise ValueError('Malformed reader block; inspect crontab manually.')
    if START in old:
        before,rest=old.split(START,1);_,after=rest.split(END,1);old=before.rstrip()+'\n'+after.lstrip('\n')
    if remove:return old.rstrip()+'\n'
    command='/bin/bash '+shlex.quote(str(repo/'scripts'/'run-replies.sh')).replace('%',r'\%')
    return old.rstrip()+'\n\n'+START+'\n# Weekdays 09:00 America/Bogota = 14:00 UTC; host timezone verified UTC.\n0 14 * * 1-5 '+command+'\n'+END+'\n'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--remove',action='store_true');parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    zone=Path('/etc/timezone').read_text().strip()
    if zone not in ('Etc/UTC','UTC'):raise SystemExit('Host must use UTC. Configure the schedule for this host timezone explicitly.')
    result=subprocess.run(['crontab','-l'],capture_output=True,text=True)
    if result.returncode and 'no crontab' not in result.stderr.lower():raise SystemExit('Could not read existing crontab.')
    old=result.stdout;new=updated_crontab(old,Path(__file__).resolve().parent.parent,args.remove)
    if args.preview:print(new,end='');return
    state=Path.home()/'.local/state/outreach-workbench/reader';state.mkdir(parents=True,exist_ok=True,mode=0o700)
    backup=state/('crontab-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.backup')
    fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(old)
    subprocess.run(['crontab','-'],input=new,text=True,check=True)
    installed=subprocess.check_output(['crontab','-l'],text=True)
    if installed!=new:raise SystemExit('Installed crontab does not match; inspect it before continuing.')
    print('Reader schedule '+('removed' if args.remove else 'installed: weekdays 09:00 Bogotá / 14:00 UTC')+'. Existing jobs preserved. Backup: '+str(backup))
if __name__=='__main__':main()
