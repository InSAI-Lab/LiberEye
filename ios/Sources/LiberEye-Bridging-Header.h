//
//  LiberEye-Bridging-Header.h
//  LiberEye
//
//  Bridging header for HeyCyan SDK (Objective-C)
//

#ifndef LiberEye_Bridging_Header_h
#define LiberEye_Bridging_Header_h

#if defined(LIBEREYE_WITH_HEYCYAN)
// HeyCyan SDK Framework Headers
#import <QCSDK/QCSDK.h>
#import <QCSDK/QCSDKManager.h>
#import <QCSDK/QCSDKCmdCreator.h>
#import <QCSDK/QCSDKHelper.h>
#import <QCSDK/QCVersionHelper.h>
#import <QCSDK/OdmBleConstants.h>
#import <QCSDK/QCDFU_Utils.h>
#import <QCSDK/QCVolumeInfoModel.h>

// Local SDK Headers (Bluetooth Central Manager)
#import "HeyCyanSDK/Headers/QCCentralManager.h"
#import "HeyCyanSDK/Headers/QCScanViewController.h"

#endif

#endif /* LiberEye_Bridging_Header_h */
