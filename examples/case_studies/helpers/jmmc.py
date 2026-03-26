from __future__ import annotations

from astropy.samp import SAMPIntegratedClient
client = SAMPIntegratedClient()

def sendOiFitsWithSAMP(filenames):
    """ Loop and send each files through SAMP usig table.load.fits messages. """
    try:
        if not client.is_connected:
            client.connect()            
        for url in filenames:
            #input(f"Press Enter to send {url} ...")        
            message = { "samp.mtype" : "table.load.fits", "samp.params" : {"url" : url} }
            receivers = [ client.get_metadata(id)['samp.name'] for id in client.notify_all(message)]
            print( f"'{url}' sent to {', '.join(receivers)}" )        
    except:
        print(f"Error trying to send a SAMP message. \nPlease check that you are running a VO compliant application ( with table.load.fits support ). \nYou can try :")
        print(" - OIFitsExplorer ( https://www.jmmc.fr/oifitsexplorer ) ")    
        print(" - OImaging       ( https://www.jmmc.fr/oimaging ) - only use the last submitted oifits")    
        print(" - LITpro         ( https://www.jmmc.fr/litpro ) ") 
