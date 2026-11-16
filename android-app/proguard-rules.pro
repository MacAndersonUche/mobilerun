# Add project specific ProGuard rules here.
-keep class ai.mobilerun.selfhosted.** { *; }
-keepclassmembers class ai.mobilerun.selfhosted.** { *; }

# Gson
-keepattributes Signature
-keepattributes *Annotation*
-keep class com.google.gson.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
