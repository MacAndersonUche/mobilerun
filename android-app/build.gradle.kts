plugins {
    id("com.android.application") version "8.7.3"
    id("org.jetbrains.kotlin.android") version "2.1.0"
    id("org.jetbrains.kotlin.plugin.compose") version "2.1.0"
}

android {
    namespace = "ai.mobilerun.selfhosted"
    compileSdk = 35

    defaultConfig {
        applicationId = "ai.mobilerun.selfhosted"
        minSdk = 26
        targetSdk = 35
        
        // Version from GitHub Actions (CI overrides with run_number); local default for assembleRelease
        versionCode = (project.findProperty("VERSION_CODE") as String?)?.toIntOrNull() ?: 400
        versionName = (project.findProperty("VERSION_NAME") as String?) ?: "1.0.400"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Baked production endpoints — no manual URL / sign-in required
        buildConfigField(
            "String",
            "DEFAULT_CLOUD_HTTP",
            "\"https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com\"",
        )
        buildConfigField(
            "String",
            "DEFAULT_CLOUD_WS",
            "\"wss://sv7144gijj.execute-api.eu-west-2.amazonaws.com/prod\"",
        )
        buildConfigField(
            "String",
            "PAIR_UI_HINT",
            "\"https://macsmobilerun.netlify.app\"",
        )
    }

    signingConfigs {
        create("release") {
            // Use committed debug keystore for consistent signing across builds
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.15"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.activity:activity-compose:1.9.3")
    
    // Compose
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    
    // WebSocket & HTTP
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.code.gson:gson:2.11.0")
    // Cognito Hosted UI via Custom Tabs (PKCE); device-code flow needs no extra lib
    implementation("androidx.browser:browser:1.8.0")
    // Long-lived device credential storage
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    
    // QR Code scanning
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")
    
    // Testing
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
