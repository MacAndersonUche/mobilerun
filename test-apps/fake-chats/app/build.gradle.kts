plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ai.mobilerun.fakechats"
    compileSdk = 34

    defaultConfig {
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        // Debuggable so adb run-as can read sent_messages.jsonl in CI
        // (flavors inherit; buildTypes.debug sets debuggable).
    }

    flavorDimensions += "chatapp"
    productFlavors {
        create("whatsapp") {
            dimension = "chatapp"
            applicationId = "com.whatsapp"
            resValue("string", "app_label", "WhatsApp")
            buildConfigField("String", "FLAVOR_KEY", "\"whatsapp\"")
        }
        create("instagram") {
            dimension = "chatapp"
            applicationId = "com.instagram.android"
            resValue("string", "app_label", "Instagram")
            buildConfigField("String", "FLAVOR_KEY", "\"instagram\"")
        }
        create("messenger") {
            dimension = "chatapp"
            applicationId = "com.facebook.orca"
            resValue("string", "app_label", "Messenger")
            buildConfigField("String", "FLAVOR_KEY", "\"messenger\"")
        }
        create("telegram") {
            dimension = "chatapp"
            applicationId = "org.telegram.messenger"
            resValue("string", "app_label", "Telegram")
            buildConfigField("String", "FLAVOR_KEY", "\"telegram\"")
        }
        create("tinder") {
            dimension = "chatapp"
            applicationId = "com.tinder"
            resValue("string", "app_label", "Tinder")
            buildConfigField("String", "FLAVOR_KEY", "\"tinder\"")
        }
        create("bumble") {
            dimension = "chatapp"
            applicationId = "com.bumble.app"
            resValue("string", "app_label", "Bumble")
            buildConfigField("String", "FLAVOR_KEY", "\"bumble\"")
        }
        create("hinge") {
            dimension = "chatapp"
            applicationId = "co.hinge.app"
            resValue("string", "app_label", "Hinge")
            buildConfigField("String", "FLAVOR_KEY", "\"hinge\"")
        }
    }

    buildTypes {
        debug {
            isDebuggable = true
        }
        release {
            isMinifyEnabled = false
            isDebuggable = true // keep run-as for CI asserts even on "release" flavor builds
        }
    }

    buildFeatures {
        buildConfig = true
        viewBinding = false
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
}
