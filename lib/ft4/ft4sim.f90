program ft4sim

! Generate simulated signals for experimental "FT4" mode 

  use wavhdr
  use packjt77
  include 'ft4_params.f90'               !Set various constants
  type(hdr) h                            !Header for .wav file
  character arg*32,fname*17
  character msg37*37,msgsent37*37
  character c77*77
  complex c0(0:NMAX-1)
  complex c(0:NMAX-1)
  real wave(NMAX)
  integer itone(NN)
  integer pack_status
  integer*1 msgbits(77)
  integer*2 iwave(NMAX)                  !Generated full-length waveform
  integer icos4(4)
  real drift_rate
  data icos4/0,1,3,2/
  
! Get command-line argument(s)
  nargs=iargc()
  drift_rate=0.0
  if(nargs.ne.7 .and. nargs.ne.8) then
     print*,'Usage:    ft4sim "message"               f0   DT fdop del nfiles snr [drift_hz_s]'
     print*,'Examples: ft4sim "CQ W9XYZ EN37"        1500 0.0  0.1 1.0   10   -15'
     print*,'          ft4sim "K1ABC W9XYZ R 539 WI" 1500 0.0  0.1 1.0   10   -15'
     go to 999
  endif
  call getarg(1,msg37)                   !Message to be transmitted
  call getarg(2,arg)
  read(arg,*) f0                         !Frequency (only used for single-signal)
  call getarg(3,arg)
  read(arg,*) xdt                        !Time offset from nominal (s)
  call getarg(4,arg)
  read(arg,*) fspread                    !Watterson frequency spread (Hz)
  call getarg(5,arg)
  read(arg,*) delay                      !Watterson delay (ms)
  call getarg(6,arg)
  read(arg,*) nfiles                     !Number of files
  call getarg(7,arg)
  read(arg,*) snrdb                      !SNR_2500
  if(nargs.eq.8) then
     call getarg(8,arg)
     read(arg,*) drift_rate                !Linear Doppler rate, Hz/s
  endif

  nfiles=abs(nfiles)
  twopi=8.0*atan(1.0)
  fs=12000.0                             !Sample rate (Hz)
  dt=1.0/fs                              !Sample interval (s)
  hmod=1.0                               !Modulation index (0.5 is MSK, 1.0 is FSK)
  tt=NSPS*dt                             !Duration of symbols (s)
  baud=1.0/tt                            !Keying rate (baud)
  txt=NZ2*dt                             !Transmission length (s)

  bandwidth_ratio=2500.0/(fs/2.0)
  sig=sqrt(2*bandwidth_ratio) * 10.0**(0.05*snrdb)
  if(snrdb.gt.90.0) sig=1.0

  ! Source-encode, then get itone()
  call genft4(msg37,0,msgsent37,msgbits,itone)
  if(trim(msgsent37).eq.'*** bad message ***') then
     print*,'Cannot encode message: ',trim(msg37)
     stop 1
  endif
  call pack77(msgsent37,i3,n3,c77,status=pack_status)
  if(pack_status.ne.PACK77_STATUS_ENCODED) then
     print*,'Cannot encode message: ',trim(msg37)
     stop 1
  endif
  write(*,*)  
  write(*,'(a9,a37,3x,a7,i1,a1,i1)') 'Message: ',msgsent37,'i3.n3: ',i3,'.',n3
  write(*,1000) f0,xdt,txt,snrdb
  write(*,'(a,f8.3,a)') 'Linear Doppler rate:',drift_rate,' Hz/s'
1000 format('f0:',f9.3,'   DT:',f6.2,'   TxT:',f6.1,'   SNR:',f6.1)
  write(*,*)  
  if(i3.eq.1) then
    write(*,*) '         mycall                         hiscall                    hisgrid'
    write(*,'(28i1,1x,i1,1x,28i1,1x,i1,1x,i1,1x,15i1,1x,3i1)') msgbits(1:77) 
  else
    write(*,'(a14)') 'Message bits: '
    write(*,'(77i1)') msgbits
  endif
  write(*,*) 
  write(*,'(a17)') 'Channel symbols: '
  write(*,'(76i1)') itone
  write(*,*)  

  call sgran()

  fsample=12000.0
  icmplx=1
  call gen_ft4wave(itone,NN,NSPS,fsample,f0,c0,wave,icmplx,NMAX)
  call apply_linear_chirp(c0,NZ2,fsample,drift_rate)

  k=nint((xdt+0.5)/dt)-NSPS
  c0=cshift(c0,-k)
  if(k.gt.0) c0(0:k-1)=0.0
  if(k.lt.0) c0(NMAX+k:NMAX-1)=0.0

  do ifile=1,nfiles
     c=c0
     if(fspread.ne.0.0 .or. delay.ne.0.0) call watterson(c,NMAX,NZ,fs,delay,fspread)
     c=sig*c
     wave=real(c)
     peak=maxval(abs(wave))
     nslots=1
   
     if(snrdb.lt.90) then
        do i=1,NMAX                   !Add gaussian noise at specified SNR
           xnoise=gran()
           wave(i)=wave(i) + xnoise
        enddo
     endif

     gain=100.0
     if(snrdb.lt.90.0) then
       wave=gain*wave
     else
       datpk=maxval(abs(wave))
       fac=32766.9/datpk
       wave=fac*wave
     endif
     if(any(abs(wave).gt.32767.0)) print*,"Warning - data will be clipped."
     iwave=nint(wave)
     h=default_header(12000,NMAX)
     write(fname,1102) ifile
1102 format('000000_',i6.6,'.wav')
     open(10,file=fname,status='replace',access='stream')
     write(10) h,iwave                !Save to *.wav file
     close(10)
     write(*,1110) ifile,xdt,f0,snrdb,fname
1110 format(i4,f7.2,f8.2,f7.1,2x,a17)
  enddo
  
999 end program ft4sim

subroutine apply_linear_chirp(c,n,fsample,drift_rate)

! Apply a deterministic linear Doppler rate around the waveform midpoint.
! Instantaneous offset: df(t) = drift_rate * (t - T/2).
! This keeps f0 as the midpoint frequency so static offset is not mixed
! into the deterministic Doppler-rate benchmark.

  implicit none
  integer, intent(in) :: n
  real, intent(in) :: fsample,drift_rate
  complex, intent(inout) :: c(0:n-1)
  integer :: i
  real(8) :: t,tmid,phase,pi

  if(drift_rate.eq.0.0) return
  pi=4.0d0*atan(1.0d0)
  tmid=0.5d0*dble(n-1)/dble(fsample)
  do i=0,n-1
     t=dble(i)/dble(fsample)-tmid
     phase=pi*dble(drift_rate)*t*t
     c(i)=c(i)*cmplx(cos(phase),sin(phase))
  enddo

  return
end subroutine apply_linear_chirp
