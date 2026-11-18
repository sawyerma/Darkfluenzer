# DarkStudio – Protobuf-Feldliste (aus Descriptor-Compiler)

Jedes Feld mit Typ und fester Tag-Nummer. Quelle: sechs kompilierte Studio-Proto-Dateien.

## studio_common.proto

### StudioVec2

```proto
double x = 1;
double y = 2;
```

### StudioVec3

```proto
double x = 1;
double y = 2;
double z = 3;
```

### StudioQuat

```proto
double w = 1;
double x = 2;
double y = 3;
double z = 4;
```

### StudioTransform

```proto
StudioVec3 translation_m = 1;
StudioQuat rotation = 2;
StudioVec3 scale = 3;
```

### StudioRGBA

```proto
double r = 1;
double g = 2;
double b = 3;
double a = 4;
```

### StudioTimeSpan

```proto
uint64 start_frame = 1;
uint64 end_frame_exclusive = 2;
uint32 fps_num = 3;
uint32 fps_den = 4;
```

### StudioFrameSize

```proto
uint32 width = 1;
uint32 height = 2;
```

### StudioRational

```proto
uint64 numerator = 1;
uint64 denominator = 2;
```

### StudioValue

```proto
string text = 1;
sint64 integer = 2;
double number = 3;
bool boolean = 4;
StudioAssetRef asset = 5;
StudioVec3 vector3 = 6;
StudioRGBA rgba = 7;
StudioStringList string_list = 8;
```

### StudioStringList

```proto
repeated string values = 1;
```

### StudioParameter

```proto
string key = 1;
StudioValue value = 2;
string unit = 3;
```

### StudioParameterSpec

```proto
string key = 1;
StudioNodePortKind kind = 2;
bool required = 3;
StudioValue default_value = 4;
optional double minimum = 5;
optional double maximum = 6;
repeated string allowed = 7;
string label = 8;
bool expert = 9;
string unit = 10;
```

### StudioAssetRef

```proto
string asset_id = 1;
string sha256 = 2;
StudioMediaKind kind = 3;
string mime = 4;
uint64 byte_size = 5;
StudioFrameSize dimensions = 6;
uint64 duration_ms = 7;
uint32 fps_num = 8;
uint32 fps_den = 9;
string source = 10;
int64 created_unix_ms = 11;
string content_tier = 12;
uint64 existing_media_id = 13;
uint64 existing_reference_id = 14;
uint64 revision = 15;
bool removed = 16;
```

### StudioReference

```proto
string reference_binding_id = 1;
StudioAssetRef asset = 2;
repeated StudioReferenceRole roles = 3;
string shot_id = 4;
string actor_id = 5;
double strength = 6;
uint64 start_frame = 7;
uint64 end_frame_exclusive = 8;
bool approved_for_provider = 9;
string rights_status = 10;
string source_label = 11;
string note = 12;
uint64 revision = 13;
```

### StudioCharacterRef

```proto
uint64 character_id = 1;
uint64 character_revision = 2;
string display_name = 3;
string sheet_asset_id = 4;
string synthetic_identity_key = 5;
```

### StudioLoraRef

```proto
string lora_key = 1;
string architecture = 2;
string base_engine = 3;
string sha256 = 4;
uint64 revision = 5;
optional double strength = 6;
StudioEvidence qualification = 7;
```

### StudioModelRef

```proto
string model_id = 1;
string architecture = 2;
StudioProviderKind provider_kind = 3;
string provider_account_id = 4;
string remote_model_id = 5;
string sha256 = 6;
string model_revision = 7;
StudioEvidence qualification = 8;
```

### StudioLookRef

```proto
string look_id = 1;
uint64 revision = 2;
string sha256 = 3;
```

### StudioMoney

```proto
string currency = 1;
string decimal_amount = 2;
```

### StudioCost

```proto
StudioMoney estimated = 1;
StudioMoney committed = 2;
StudioMoney actual = 3;
uint64 input_tokens = 4;
uint64 output_tokens = 5;
uint64 credit_units = 6;
string price_basis = 7;
bool known = 8;
```

### StudioError

```proto
string code = 1;
string message = 2;
string field_path = 3;
bool retryable = 4;
string provider_request_id = 5;
int64 occurred_unix_ms = 6;
```

### StudioQualityCheck

```proto
string check_id = 1;
string metric = 2;
StudioReviewVerdict verdict = 3;
optional double value = 4;
optional double threshold = 5;
string unit = 6;
string reason = 7;
string inspector_version = 8;
string model_sha256 = 9;
string asset_sha256 = 10;
int64 evaluated_unix_ms = 11;
StudioEvidence evidence = 12;
bool required = 13;
```

### StudioOutputSpec

```proto
StudioMediaKind kind = 1;
StudioFrameSize output_dimensions = 2;
StudioFrameSize native_dimensions = 3;
uint32 fps_num = 4;
uint32 fps_den = 5;
uint64 duration_ms = 6;
string container = 7;
string codec = 8;
string pixel_format = 9;
uint32 image_count = 10;
uint32 sample_rate_hz = 11;
uint32 audio_channels = 12;
string aspect_label = 13;
uint32 bitrate_kbps = 14;
bool alpha = 15;
bool upscale = 16;
string color_space = 17;
uint32 variant_count = 18;
```

### StudioProviderChoice

```proto
StudioProviderPolicy policy = 1;
StudioProviderKind preferred_kind = 2;
string account_id = 3;
string model_id = 4;
bool allow_cloud = 5;
bool allow_fallback = 6;
repeated string fallback_model_ids = 7;
StudioMoney cost_ceiling = 8;
bool reference_transfer_allowed = 9;
```

### StudioOutputProfile

```proto
string profile_id = 1;
string label = 2;
StudioOutputSpec output = 3;
StudioEvidence qualification = 4;
bool active = 5;
```

### StudioPageInfo

```proto
string next_page_token = 1;
bool has_more = 2;
uint64 domain_version = 3;
uint32 returned_count = 4;
```

## studio_catalog.proto

### StudioTaskProfile

```proto
string task_profile_id = 1;
StudioTaskKind kind = 2;
string title = 3;
string group = 4;
string content_tier = 5;
repeated StudioReferenceRole accepted_reference_roles = 6;
repeated StudioNodePortKind required_inputs = 7;
StudioOutputSpec default_output = 8;
repeated StudioOutputProfile output_profiles = 9;
string character_architecture = 10;
StudioProviderPolicy locality = 11;
string active_recipe_id = 12;
uint64 active_recipe_revision = 13;
StudioCapabilityStatus capability = 14;
repeated string problems = 15;
bool customer_enabled = 16;
bool operator_enabled = 17;
uint64 version = 18;
```

### StudioRecipeVersion

```proto
string recipe_id = 1;
uint64 revision = 2;
string title = 3;
string task_profile_id = 4;
string flow_id = 5;
uint64 flow_revision = 6;
repeated StudioParameter exposed_parameters = 7;
StudioProviderChoice provider_policy = 8;
StudioEvidence qualification = 9;
repeated string qualification_evidence_ids = 10;
bool active_standard = 11;
bool disabled = 12;
string failure_reason = 13;
string content_tier = 14;
string architecture = 15;
StudioOutputSpec output_spec = 16;
string recipe_sha256 = 17;
int64 created_unix_ms = 18;
string created_by = 19;
StudioApprovalPolicy default_approval = 20;
uint32 retry_limit = 21;
StudioMoney default_budget = 22;
```

### StudioCompatibility

```proto
StudioModelRef model = 1;
StudioLoraRef lora = 2;
bool compatible = 3;
StudioCapabilityStatus status = 4;
repeated string reasons = 5;
repeated StudioReferenceRole supported_reference_roles = 6;
repeated StudioNodePortKind supported_control_types = 7;
StudioEvidence mac_m4_evidence = 8;
```

### StudioModelCapability

```proto
string capability_id = 1;
StudioModelRef model = 2;
string display_name = 3;
StudioTaskKind task = 4;
repeated StudioNodePortKind inputs = 5;
repeated StudioNodePortKind outputs = 6;
repeated StudioReferenceRole reference_roles = 7;
repeated string lora_architectures = 8;
repeated string compatible_control_models = 9;
repeated StudioFrameSize allowed_resolutions = 10;
uint64 max_duration_ms = 11;
uint32 max_fps_num = 12;
uint32 max_fps_den = 13;
uint32 max_references = 14;
bool supports_start_end_frames = 15;
bool supports_pose = 16;
bool supports_depth = 17;
bool supports_mask = 18;
bool supports_motion = 19;
bool supports_audio = 20;
bool supports_lora = 21;
bool supports_mps = 22;
bool supports_batch = 23;
string workflow_key = 24;
string checkpoint_sha256 = 25;
StudioEvidence evidence = 26;
StudioCapabilityStatus available = 27;
string license_id = 28;
string license_url = 29;
string qualification_note = 30;
uint64 estimated_unified_memory_bytes = 31;
double measured_p50_seconds = 32;
double measured_p95_seconds = 33;
int64 last_qualified_unix_ms = 34;
string node_adapter_id = 35;
repeated StudioParameterSpec parameters = 36;
bool supports_seed = 37;
bool supports_inpaint = 38;
bool supports_video_control = 39;
bool supports_vision = 40;
bool supports_structured_output = 41;
```

### StudioModelCatalog

```proto
repeated StudioModelCapability models = 1;
repeated StudioCompatibility compatibilities = 2;
uint64 version = 3;
int64 updated_unix_ms = 4;
```

### StudioComparisonItem

```proto
string candidate_id = 1;
StudioModelRef model = 2;
string workflow_key = 3;
StudioAssetRef output = 4;
repeated StudioQualityCheck checks = 5;
StudioCost cost = 6;
uint64 elapsed_ms = 7;
StudioError error = 8;
StudioEvidence evidence = 9;
string parameter_sha256 = 10;
```

### StudioComparisonRun

```proto
string comparison_id = 1;
string task_profile_id = 2;
string reference_set_sha256 = 3;
string prompt_sha256 = 4;
repeated StudioComparisonItem candidates = 5;
string selected_candidate_id = 6;
string operator_note = 7;
uint64 revision = 8;
int64 created_unix_ms = 9;
```

### StudioProviderAccount

```proto
string account_id = 1;
string alias = 2;
StudioProviderKind provider = 3;
bool enabled = 4;
bool secret_present = 5;
string credential_status = 6;
string auth_status = 7;
string last_error_code = 8;
int64 last_test_unix_ms = 9;
repeated string available_model_ids = 10;
uint32 requests_per_minute_limit = 11;
uint32 tokens_per_minute_limit = 12;
uint32 max_parallel_jobs = 13;
uint32 timeout_ms = 14;
StudioMoney monthly_budget = 15;
StudioMoney spent_this_month = 16;
StudioMoney reserved_budget = 17;
bool cloud_data_transfer_enabled = 18;
bool media_transfer_enabled = 19;
bool active_for_new_jobs = 20;
string provider_catalog_revision = 21;
int64 catalog_updated_unix_ms = 22;
uint64 revision = 23;
string provider_endpoint_id = 24;
```

### StudioProviderModel

```proto
string account_id = 1;
string model_id = 2;
string title = 3;
StudioProviderKind provider = 4;
repeated StudioModelRole roles = 5;
bool text = 6;
bool vision = 7;
bool images = 8;
bool video = 9;
bool audio = 10;
bool structured_output = 11;
uint64 context_tokens = 12;
uint64 max_output_tokens = 13;
StudioMoney estimated_input_token_cost = 14;
StudioMoney estimated_output_token_cost = 15;
string model_version = 16;
StudioCapabilityStatus availability = 17;
string unavailable_reason = 18;
int64 verified_unix_ms = 19;
```

### StudioRoleBinding

```proto
string binding_id = 1;
StudioModelRole role = 2;
string scope = 3;
string scope_id = 4;
string account_id = 5;
string model_id = 6;
string local_workflow_key = 7;
StudioProviderPolicy policy = 8;
bool fallback_enabled = 9;
repeated string fallback_model_ids = 10;
optional double temperature = 11;
optional double top_p = 12;
uint32 max_output_tokens = 13;
uint32 timeout_ms = 14;
StudioMoney cost_ceiling = 15;
bool allow_customer_text_transfer = 16;
bool allow_reference_media_transfer = 17;
uint64 revision = 18;
string prompt_template_id = 19;
uint64 prompt_template_revision = 20;
```

### StudioProviderUsage

```proto
string usage_id = 1;
string account_id = 2;
string model_id = 3;
string production_id = 4;
string node_run_id = 5;
string provider_request_id = 6;
uint64 input_tokens = 7;
uint64 output_tokens = 8;
uint64 billed_units = 9;
StudioCost cost = 10;
int64 started_unix_ms = 11;
int64 finished_unix_ms = 12;
StudioError error = 13;
string result_asset_sha256 = 14;
```

### StudioProviderSettings

```proto
repeated StudioProviderAccount accounts = 1;
repeated StudioProviderModel models = 2;
repeated StudioRoleBinding bindings = 3;
StudioProviderPolicy default_policy = 4;
bool external_providers_master_enabled = 5;
StudioMoney global_monthly_budget = 6;
StudioMoney global_remaining_budget = 7;
uint64 version = 8;
bool customer_conversation_external_enabled = 9;
```

### StudioCharacterSheet

```proto
StudioCharacterRef character = 1;
repeated StudioAssetRef identity_references = 2;
repeated StudioLoraRef loras = 3;
StudioLookRef default_look = 4;
repeated StudioLookPreset looks = 5;
StudioEvidence identity_qualification = 6;
string trigger = 7;
string class_word = 8;
uint32 usable_training_images = 9;
uint32 required_training_images = 10;
uint64 revision = 11;
int64 updated_unix_ms = 12;
string status_reason = 13;
```

### StudioLookPreset

```proto
StudioLookRef look = 1;
string title = 2;
repeated StudioReference reference_materials = 3;
repeated StudioReference reference_clothing = 4;
repeated StudioReference reference_styles = 5;
repeated StudioReference reference_lighting = 6;
StudioCharacterRef character = 7;
StudioLoraRef lora = 8;
repeated StudioParameter render_parameters = 9;
bool active = 10;
int64 created_unix_ms = 11;
string color_profile = 12;
string negative_prompt = 13;
```

### StudioTrainingRun

```proto
string training_id = 1;
StudioCharacterRef character = 2;
string dataset_id = 3;
string dataset_sha256 = 4;
StudioModelRef base_model = 5;
StudioLoraRef target_lora = 6;
string registered_workflow_key = 7;
string underlying_job_id = 8;
StudioRunStatus status = 9;
uint64 step_current = 10;
uint64 step_total = 11;
double loss = 12;
string checkpoint_asset_id = 13;
uint32 rank = 14;
uint64 revision = 15;
uint64 started_unix_ms = 16;
uint64 updated_unix_ms = 17;
StudioError error = 18;
StudioEvidence qualification = 19;
```

### StudioProject

```proto
string project_id = 1;
string name = 2;
StudioCharacterRef default_character = 3;
StudioLookRef default_look = 4;
StudioSource source = 5;
string source_reference = 6;
repeated string production_ids = 7;
repeated string asset_ids = 8;
string active_storyboard_id = 9;
uint64 active_storyboard_revision = 10;
uint64 revision = 11;
int64 created_unix_ms = 12;
int64 updated_unix_ms = 13;
bool archived = 14;
string owner = 15;
```

### StudioResourceState

```proto
uint64 unified_memory_total_bytes = 1;
uint64 unified_memory_available_bytes = 2;
uint64 unified_memory_reserved_bytes = 3;
uint64 swap_used_bytes = 4;
uint64 gpu_busy_percent = 5;
uint32 running_media_jobs = 6;
uint32 queued_media_jobs = 7;
uint32 running_text_jobs = 8;
uint32 running_blender_jobs = 9;
uint32 pending_customer_jobs = 10;
bool admission_paused = 11;
string admission_reason = 12;
int64 measured_unix_ms = 13;
double backend_loop_lag_ms = 14;
string media_instance = 15;
string text_instance = 16;
repeated StudioWorkerStatus workers = 17;
```

### StudioWorkerStatus

```proto
string worker_id = 1;
StudioResourceClass resource = 2;
string version = 3;
StudioCapabilityStatus state = 4;
string current_production_id = 5;
string current_node_run_id = 6;
string error = 7;
int64 last_heartbeat_unix_ms = 8;
uint64 estimated_need_bytes = 9;
```

### StudioCatalog

```proto
repeated StudioTaskProfile tasks = 1;
repeated StudioRecipeVersion recipes = 2;
repeated StudioCharacterSheet characters = 3;
repeated StudioOutputProfile output_profiles = 4;
StudioModelCatalog model_catalog = 5;
repeated StudioLookPreset looks = 6;
uint64 version = 7;
int64 updated_unix_ms = 8;
```

### StudioPromptTemplate

```proto
string template_id = 1;
uint64 revision = 2;
string title = 3;
StudioModelRole role = 4;
string system_text = 5;
string user_text_template = 6;
repeated StudioPromptVariable variables = 7;
repeated string allowed_output_schema_ids = 8;
StudioProviderPolicy provider_policy = 9;
string language_code = 10;
bool enabled = 11;
bool customer_approved = 12;
string content_tier = 13;
int64 created_unix_ms = 14;
string sha256 = 15;
```

### StudioPromptVariable

```proto
string name = 1;
StudioNodePortKind kind = 2;
bool required = 3;
string source_field_path = 4;
StudioValue default_value = 5;
string label = 6;
```

### StudioAudioProviderPreset

```proto
string preset_id = 1;
uint64 revision = 2;
string name = 3;
StudioProviderChoice provider = 4;
string voice_model_id = 5;
string voice_id = 6;
string language_code = 7;
optional double speaking_rate = 8;
optional double pitch = 9;
optional double expression_strength = 10;
bool lip_sync_enabled = 11;
string lip_sync_model_id = 12;
StudioEvidence qualification = 13;
```

## studio_creative.proto

### StudioBriefFact

```proto
string field_path = 1;
StudioValue value = 2;
string source_item_id = 3;
string source_asset_id = 4;
string certainty = 5;
bool operator_confirmed = 6;
int64 observed_unix_ms = 7;
```

### StudioCreativeBrief

```proto
string brief_id = 1;
uint64 revision = 2;
string title = 3;
string original_wish = 4;
string normalized_wish = 5;
StudioTaskKind task = 6;
string language_code = 7;
string setting = 8;
string plot = 9;
string desired_mood = 10;
string style = 11;
string wardrobe = 12;
string character_action = 13;
string camera_direction = 14;
StudioCharacterRef target_character = 15;
StudioLookRef look = 16;
repeated StudioReference references = 17;
StudioOutputSpec output = 18;
repeated StudioBriefFact facts = 19;
repeated string missing_fields = 20;
repeated string questions_to_customer = 21;
bool ready_to_plan = 22;
bool operator_approved = 23;
StudioProviderChoice provider_policy = 24;
string content_tier = 25;
string request_context_id = 26;
uint64 source_revision = 27;
int64 created_unix_ms = 28;
string prompt_template_id = 29;
uint64 prompt_template_revision = 30;
StudioModelRef authored_by_model = 31;
string author_run_id = 32;
string negative_constraints = 33;
uint32 scene_count_hint = 34;
```

### StudioScriptVersion

```proto
string script_id = 1;
uint64 revision = 2;
string brief_id = 3;
uint64 brief_revision = 4;
string title = 5;
string logline = 6;
string synopsis = 7;
string plot = 8;
repeated StudioScriptScene scenes = 9;
string language_code = 10;
StudioModelRef author_model = 11;
string prompt_template_id = 12;
uint64 prompt_template_revision = 13;
int64 created_unix_ms = 14;
string review_status = 15;
repeated StudioDirectorNote notes = 16;
```

### StudioScriptScene

```proto
string scene_id = 1;
uint32 order = 2;
string heading = 3;
string description = 4;
string location = 5;
string time_of_day = 6;
string action = 7;
repeated StudioDialogueLine dialogue = 8;
repeated string actor_ids = 9;
uint64 planned_duration_ms = 10;
repeated string shot_ids = 11;
repeated string props = 12;
string emotional_arc = 13;
string continuity_rules = 14;
```

### StudioDialogueLine

```proto
string dialogue_id = 1;
string actor_id = 2;
string speaker_name = 3;
string text = 4;
string delivery = 5;
uint64 offset_ms = 6;
uint64 duration_ms = 7;
string audio_asset_id = 8;
string language_code = 9;
```

### StudioDirectorNote

```proto
string note_id = 1;
string target_scene_id = 2;
string target_shot_id = 3;
string finding = 4;
string proposed_change = 5;
StudioModelRef model = 6;
int64 created_unix_ms = 7;
bool operator_accepted = 8;
string affected_field_path = 9;
```

### StudioStoryboard

```proto
string storyboard_id = 1;
uint64 revision = 2;
string project_id = 3;
string brief_id = 4;
uint64 brief_revision = 5;
string script_id = 6;
uint64 script_revision = 7;
string title = 8;
repeated StudioScene scenes = 9;
StudioOutputSpec output_spec = 10;
StudioRunStatus status = 11;
StudioApprovalPolicy review_policy = 12;
string notes = 13;
int64 updated_unix_ms = 14;
string preview_asset_id = 15;
string director_model_id = 16;
```

### StudioScene

```proto
string scene_id = 1;
uint64 revision = 2;
uint32 sequence = 3;
string name = 4;
string action = 5;
string setting = 6;
repeated StudioShot shots = 7;
StudioTimeSpan time_range = 8;
repeated StudioReference references = 9;
repeated string continuity_constraints = 10;
StudioLookRef look = 11;
StudioCharacterRef default_character = 12;
StudioAssetRef preview_asset = 13;
bool approved = 14;
string scene_spec_id = 15;
uint64 scene_spec_revision = 16;
string music_cue = 17;
```

### StudioShot

```proto
string shot_id = 1;
string scene_id = 2;
uint64 revision = 3;
uint32 order = 4;
string title = 5;
string action = 6;
string image_prompt = 7;
string video_prompt = 8;
string negative_prompt = 9;
string dialogue_notes = 10;
StudioTimeSpan time = 11;
StudioCameraShot camera = 12;
repeated StudioShotActor actors = 13;
repeated StudioReference references = 14;
StudioCharacterRef main_character = 15;
StudioLoraRef lora = 16;
StudioLookRef look = 17;
StudioModelRef image_model = 18;
StudioModelRef video_model = 19;
StudioAssetRef start_frame = 20;
StudioAssetRef end_frame = 21;
repeated StudioTimedFrame keyframes = 22;
StudioAssetRef guide_video = 23;
StudioAssetRef draft_video = 24;
StudioAssetRef final_video = 25;
StudioOutputSpec output = 26;
repeated StudioQualityCheck checks = 27;
StudioReviewVerdict verdict = 28;
StudioProviderChoice provider_policy = 29;
repeated StudioGuideTransfer guide_channels = 30;
uint64 seed = 31;
bool seed_specified = 32;
StudioBlockingMode blocking_mode = 33;
string transition_in = 34;
string transition_out = 35;
uint64 transition_in_ms = 36;
uint64 transition_out_ms = 37;
string scene_spec_id = 38;
uint64 scene_spec_revision = 39;
repeated StudioDialogueLine dialogue = 40;
string sound_effects = 41;
StudioRunStatus status = 42;
```

### StudioCameraShot

```proto
string shot_size = 1;
string angle = 2;
StudioCameraControl control = 3;
StudioTransform start = 4;
StudioTransform end = 5;
double lens_mm = 6;
double focus_distance_m = 7;
double fstop = 8;
double sensor_width_mm = 9;
repeated StudioCameraKeyframe keyframes = 10;
string camera_rig_id = 11;
string camera_path_id = 12;
string direction_notes = 13;
bool inherit_from_previous_shot = 14;
```

### StudioTimedFrame

```proto
uint64 frame = 1;
StudioAssetRef image = 2;
double strength = 3;
string note = 4;
```

### StudioShotActor

```proto
string actor_id = 1;
StudioCharacterRef character = 2;
StudioLoraRef lora = 3;
string role = 4;
string action = 5;
string wardrobe = 6;
repeated StudioReference references = 7;
StudioTransform initial_transform = 8;
string pose_track_id = 9;
string motion_track_id = 10;
bool use_source_identity = 11;
```

### StudioPoseJoint

```proto
string joint_id = 1;
StudioVec3 position = 2;
double confidence = 3;
bool inferred = 4;
bool operator_adjusted = 5;
```

### StudioPoseFrame

```proto
uint64 frame = 1;
string actor_id = 2;
repeated StudioPoseJoint joints = 3;
StudioAssetRef source_asset = 4;
string extractor_id = 5;
```

### StudioPoseTrack

```proto
string track_id = 1;
string actor_id = 2;
uint64 revision = 3;
repeated StudioPoseFrame frames = 4;
uint32 fps_num = 5;
uint32 fps_den = 6;
string skeleton_id = 7;
StudioAssetRef pose_control_video = 8;
```

### StudioMotionTrack

```proto
string track_id = 1;
string actor_id = 2;
uint64 revision = 3;
repeated StudioTransformKeyframe transforms = 4;
repeated StudioPoseFrame poses = 5;
StudioAssetRef motion_video = 6;
uint32 fps_num = 7;
uint32 fps_den = 8;
string coordinate_system = 9;
```

### StudioControlSettings

```proto
bool use_pose = 1;
bool use_depth = 2;
bool use_mask = 3;
bool use_edges = 4;
bool use_motion = 5;
bool preserve_identity = 6;
bool preserve_clothing = 7;
bool preserve_background = 8;
bool preserve_camera = 9;
optional double pose_strength = 10;
optional double identity_strength = 11;
optional double style_strength = 12;
optional double depth_strength = 13;
optional double mask_strength = 14;
optional double motion_strength = 15;
repeated StudioGuideTransfer transfer = 16;
StudioBlockingMode blocking = 17;
string preferred_control_model_id = 18;
StudioAssetRef segmentation_mask = 19;
StudioAssetRef pose_map = 20;
StudioAssetRef depth_map = 21;
StudioAssetRef edge_map = 22;
string target_actor_id = 23;
```

### StudioSceneSpec

```proto
string scene_spec_id = 1;
uint64 revision = 2;
string scene_id = 3;
string shot_id = 4;
string scene_unit = 5;
string coordinate_system = 6;
uint32 fps_num = 7;
uint32 fps_den = 8;
uint64 frame_start = 9;
uint64 frame_end_exclusive = 10;
repeated StudioSceneObject objects = 11;
repeated StudioActorRig actors = 12;
repeated StudioCameraRig cameras = 13;
repeated StudioLightSpec lights = 14;
repeated StudioMotionTrack actor_tracks = 15;
repeated StudioReference references = 16;
StudioBlockingMode blocking_mode = 17;
repeated StudioGuideTransfer guide_passes = 18;
StudioAssetRef backdrop = 19;
string world_preset_id = 20;
string render_preset_id = 21;
uint32 max_geometry_objects = 22;
uint64 max_geometry_vertices = 23;
string spec_sha256 = 24;
string builder_version = 25;
StudioReviewVerdict review = 26;
int64 created_unix_ms = 27;
```

### StudioSceneObject

```proto
string object_id = 1;
string label = 2;
string primitive_type = 3;
StudioTransform transform = 4;
StudioVec3 dimensions_m = 5;
StudioRGBA color = 6;
string material_preset_id = 7;
string parent_object_id = 8;
bool visible = 9;
bool casts_shadow = 10;
bool is_actor_marker = 11;
string actor_id = 12;
string controlled_asset_id = 13;
repeated StudioTransformKeyframe keyframes = 14;
string physics_preset_id = 15;
```

### StudioActorRig

```proto
string actor_id = 1;
string name = 2;
StudioCharacterRef target_character = 3;
string rig_preset_id = 4;
string proxy_object_id = 5;
string motion_track_id = 6;
string pose_track_id = 7;
StudioTransform bind_transform = 8;
StudioBlockingMode blocking_mode = 9;
bool transfer_body_pose = 10;
bool transfer_facial_pose = 11;
bool transfer_position = 12;
bool transfer_source_appearance = 13;
repeated StudioReference references = 14;
```

### StudioTransformKeyframe

```proto
uint64 frame = 1;
StudioTransform transform = 2;
string interpolation = 3;
string easing = 4;
```

### StudioCameraRig

```proto
string camera_id = 1;
string name = 2;
StudioCameraControl control = 3;
string carrier_object_id = 4;
string parent_actor_id = 5;
string path_object_id = 6;
double lens_mm = 7;
double sensor_width_mm = 8;
double focus_distance_m = 9;
double fstop = 10;
repeated StudioCameraKeyframe keyframes = 11;
StudioCameraExternalInput external = 12;
StudioTransform initial_transform = 13;
bool use_carrier_translation = 14;
bool use_external_rotation = 15;
bool use_external_translation = 16;
string stabilization_preset = 17;
bool locked = 18;
```

### StudioCameraKeyframe

```proto
uint64 frame = 1;
StudioTransform transform = 2;
double lens_mm = 3;
double focus_distance_m = 4;
string interpolation = 5;
string look_at_object_id = 6;
```

### StudioCameraExternalInput

```proto
string input_id = 1;
string device_alias = 2;
string adapter_id = 3;
StudioCapabilityStatus status = 4;
StudioAssetRef recorded_track = 5;
string calibration_id = 6;
string time_sync_id = 7;
uint64 start_frame = 8;
uint64 end_frame_exclusive = 9;
bool rotation_enabled = 10;
bool translation_enabled = 11;
double yaw_offset_deg = 12;
double pitch_offset_deg = 13;
double roll_offset_deg = 14;
double smoothing = 15;
int64 latency_compensation_ms = 16;
string axis_mapping_id = 17;
string coordinate_system = 18;
repeated StudioCameraSensorSample samples = 19;
```

### StudioCameraSensorSample

```proto
uint64 relative_ns = 1;
StudioQuat rotation = 2;
StudioVec3 translation_m = 3;
bool has_translation = 4;
double confidence = 5;
uint64 sequence_no = 6;
```

### StudioLightSpec

```proto
string light_id = 1;
string kind = 2;
StudioTransform transform = 3;
double energy_w = 4;
StudioRGBA color = 5;
double size_m = 6;
double cone_angle_deg = 7;
string look_preset_id = 8;
```

### StudioGuideBundle

```proto
string guide_id = 1;
uint64 revision = 2;
string scene_spec_id = 3;
uint64 scene_spec_revision = 4;
StudioAssetRef blend_file = 5;
StudioAssetRef playblast_video = 6;
StudioAssetRef depth_video = 7;
StudioAssetRef pose_video = 8;
StudioAssetRef mask_video = 9;
StudioAssetRef normal_video = 10;
StudioAssetRef edge_video = 11;
StudioAssetRef camera_track = 12;
repeated StudioAssetRef actor_tracks = 13;
uint32 fps_num = 14;
uint32 fps_den = 15;
uint64 frame_count = 16;
repeated StudioGuideTransfer enabled_channels = 17;
string blender_version = 18;
string builder_sha256 = 19;
string guide_bundle_sha256 = 20;
StudioReviewVerdict guide_review = 21;
repeated StudioQualityCheck checks = 22;
```

### StudioGuideMatch

```proto
string guide_id = 1;
string output_asset_id = 2;
optional double pose_similarity = 3;
optional double framing_similarity = 4;
optional double camera_similarity = 5;
optional double identity_similarity = 6;
optional double temporal_jitter = 7;
optional double timing_error_ms = 8;
StudioReviewVerdict verdict = 9;
StudioEvidence evidence = 10;
repeated StudioQualityCheck checks = 11;
```

### StudioTimelineClip

```proto
string clip_id = 1;
string shot_id = 2;
string scene_id = 3;
StudioAssetRef asset = 4;
StudioSoundTrackKind track_kind = 5;
uint64 timeline_start_frame = 6;
uint64 source_start_frame = 7;
uint64 source_end_frame_exclusive = 8;
uint64 fade_in_frames = 9;
uint64 fade_out_frames = 10;
double volume_gain_db = 11;
double playback_speed = 12;
string transition = 13;
uint64 revision = 14;
bool muted = 15;
```

### StudioTimelineTrack

```proto
string track_id = 1;
StudioSoundTrackKind kind = 2;
string label = 3;
uint32 order = 4;
repeated StudioTimelineClip clips = 5;
bool muted = 6;
bool locked = 7;
uint64 revision = 8;
```

### StudioTimeline

```proto
string timeline_id = 1;
uint64 revision = 2;
string storyboard_id = 3;
uint64 storyboard_revision = 4;
repeated StudioTimelineTrack tracks = 5;
uint32 fps_num = 6;
uint32 fps_den = 7;
uint64 total_frames = 8;
StudioOutputSpec export_profile = 9;
repeated StudioQualityCheck continuity_checks = 10;
StudioReviewVerdict verdict = 11;
int64 updated_unix_ms = 12;
```

### StudioShotPreset

```proto
string preset_id = 1;
uint64 revision = 2;
string title = 3;
string category = 4;
StudioCameraShot camera = 5;
StudioBlockingMode blocking = 6;
repeated StudioSceneObject proxy_objects = 7;
repeated StudioActorRig actors = 8;
uint64 default_duration_ms = 9;
repeated StudioGuideTransfer guide_channels = 10;
string preview_asset_id = 11;
string asset_sha256 = 12;
bool enabled = 13;
```

### StudioAudioCue

```proto
string cue_id = 1;
string shot_id = 2;
string text = 3;
string language_code = 4;
string speaker_actor_id = 5;
string voice_preset_id = 6;
string voice_model_id = 7;
string sound_effect_preset_id = 8;
uint64 timeline_start_frame = 9;
uint64 duration_frames = 10;
StudioAssetRef source_audio = 11;
StudioAssetRef rendered_audio = 12;
optional double gain_db = 13;
bool generate_lipsync = 14;
StudioReviewVerdict verdict = 15;
```

### StudioSubtitleCue

```proto
string subtitle_id = 1;
string speaker_actor_id = 2;
string text = 3;
uint64 start_frame = 4;
uint64 end_frame_exclusive = 5;
string language_code = 6;
string style_preset = 7;
StudioAssetRef source = 8;
```

## studio_flow.proto

### StudioPortDefinition

```proto
string port_id = 1;
string label = 2;
StudioNodePortKind kind = 3;
bool required = 4;
bool repeated = 5;
string architecture_constraint = 6;
repeated StudioReferenceRole allowed_reference_roles = 7;
StudioValue fallback_value = 8;
```

### StudioNodeDefinition

```proto
string node_id = 1;
string node_type = 2;
uint32 node_version = 3;
string title = 4;
StudioStage stage = 5;
repeated StudioPortDefinition inputs = 6;
repeated StudioPortDefinition outputs = 7;
repeated StudioParameter parameters = 8;
StudioModelRef model = 9;
StudioLoraRef lora = 10;
StudioProviderChoice provider_policy = 11;
StudioResourceClass resource = 12;
StudioVec2 canvas_position = 13;
bool enabled = 14;
uint32 retry_limit = 15;
uint64 timeout_ms = 16;
bool cacheable = 17;
bool idempotent = 18;
bool requires_operator_review = 19;
bool has_side_effects = 20;
string adapter_id = 21;
string engine_workflow_key = 22;
uint64 engine_workflow_version = 23;
string subgroup_id = 24;
string loop_group_id = 25;
uint32 max_iterations = 26;
string condition_id = 27;
string shot_selector = 28;
StudioMoney cost_ceiling = 29;
StudioEvidence qualification = 30;
StudioCapabilityStatus availability = 31;
string description = 32;
uint64 revision = 33;
```

### StudioNodePortValue

```proto
string port_id = 1;
StudioNodePortKind kind = 2;
StudioValue scalar = 3;
repeated StudioAssetRef assets = 4;
repeated StudioReference references = 5;
StudioCharacterRef character = 6;
StudioLoraRef lora = 7;
StudioModelRef model = 8;
StudioCreativeBrief brief = 9;
StudioScriptVersion script = 10;
StudioStoryboard storyboard = 11;
StudioScene scene = 12;
StudioShot shot = 13;
StudioSceneSpec scene_spec = 14;
StudioGuideBundle guide = 15;
repeated StudioQualityCheck checks = 16;
string export_manifest_id = 17;
StudioLookRef look = 18;
string provenance_hash = 19;
```

### StudioFlowEdge

```proto
string edge_id = 1;
string source_node_id = 2;
string source_port_id = 3;
string target_node_id = 4;
string target_port_id = 5;
string condition_id = 6;
bool enabled = 7;
uint32 order = 8;
```

### StudioFlowCondition

```proto
string condition_id = 1;
string source_node_id = 2;
string source_port_id = 3;
string operator_id = 4;
StudioValue compare_value = 5;
string true_edge_id = 6;
string false_edge_id = 7;
```

### StudioStageGate

```proto
StudioStage stage = 1;
StudioApprovalPolicy policy = 2;
repeated string required_check_ids = 3;
bool require_character_master = 4;
bool require_qualified_recipe = 5;
bool require_operator_approval = 6;
bool allow_partial_failure = 7;
```

### StudioFlowDefinition

```proto
string flow_id = 1;
uint64 revision = 2;
string title = 3;
string description = 4;
string recipe_id = 5;
uint64 recipe_revision = 6;
repeated StudioNodeDefinition nodes = 7;
repeated StudioFlowEdge edges = 8;
repeated StudioFlowCondition conditions = 9;
repeated StudioStageGate stage_gates = 10;
repeated string subflow_ids = 11;
uint32 max_total_iterations = 12;
uint32 max_total_retries = 13;
StudioMoney max_cost = 14;
uint64 max_runtime_ms = 15;
bool active = 16;
bool customer_enabled = 17;
bool draft = 18;
string flow_sha256 = 19;
int64 created_unix_ms = 20;
string owner = 21;
string origin_template_id = 22;
string origin_template_revision = 23;
string content_tier = 24;
```

### StudioValidationIssue

```proto
string issue_id = 1;
string code = 2;
string node_id = 3;
string port_id = 4;
string field_path = 5;
string message = 6;
string severity = 7;
bool blocks_execution = 8;
```

### StudioFlowValidation

```proto
string flow_id = 1;
uint64 flow_revision = 2;
bool executable = 3;
repeated StudioValidationIssue issues = 4;
repeated StudioModelCapability missing_capabilities = 5;
StudioMoney estimated_cost = 6;
uint64 estimated_memory_bytes = 7;
string compile_fingerprint = 8;
StudioEvidence evidence = 9;
int64 checked_unix_ms = 10;
```

### StudioNodeRun

```proto
string node_run_id = 1;
string node_id = 2;
string production_id = 3;
string flow_id = 4;
uint64 flow_revision = 5;
string scene_id = 6;
string shot_id = 7;
uint32 iteration = 8;
uint32 attempt = 9;
StudioStepStatus status = 10;
StudioStage stage = 11;
repeated StudioNodePortValue input_values = 12;
repeated StudioNodePortValue output_values = 13;
string input_fingerprint = 14;
string output_fingerprint = 15;
repeated StudioAssetRef output_assets = 16;
StudioModelRef model = 17;
StudioLoraRef lora = 18;
string adapter_id = 19;
string workflow_key = 20;
string workflow_sha256 = 21;
string provider_request_id = 22;
string comfy_prompt_id = 23;
string worker_id = 24;
StudioResourceClass resource = 25;
uint64 progress_current = 26;
uint64 progress_total = 27;
int64 queued_unix_ms = 28;
int64 started_unix_ms = 29;
int64 updated_unix_ms = 30;
int64 finished_unix_ms = 31;
StudioError error = 32;
repeated StudioQualityCheck checks = 33;
StudioCost cost = 34;
bool cache_hit = 35;
bool result_verified = 36;
bool requires_review = 37;
uint64 revision = 38;
string last_receipt_request_id = 39;
uint64 timeout_ms = 40;
uint64 total_elapsed_ms = 41;
string retry_reason = 42;
uint64 remote_status_checked_unix_ms = 43;
```

### StudioProductionRequest

```proto
string request_id = 1;
StudioSource source = 2;
string external_order_id = 3;
string project_id = 4;
string task_profile_id = 5;
string recipe_id = 6;
uint64 recipe_revision = 7;
string flow_id = 8;
uint64 flow_revision = 9;
StudioCreativeBrief brief = 10;
StudioCharacterRef character = 11;
repeated StudioReference references = 12;
StudioOutputSpec output_spec = 13;
StudioProviderChoice provider_policy = 14;
StudioMoney cost_ceiling = 15;
StudioApprovalPolicy review_policy = 16;
StudioStage stage_policy = 17;
uint32 priority = 18;
int64 deadline_unix_ms = 19;
uint64 expected_order_revision = 20;
uint64 expected_project_revision = 21;
uint64 expected_brief_revision = 22;
bool allow_qualified_auto = 23;
string content_tier = 24;
string source_context_id = 25;
string operator_id = 26;
bool test_order = 27;
uint32 candidate_count = 28;
string selected_look_id = 29;
uint64 look_revision = 30;
StudioControlSettings controls = 31;
```

### StudioProductionReceipt

```proto
string request_id = 1;
string production_id = 2;
bool accepted = 3;
string reason_code = 4;
string detail = 5;
uint64 production_revision = 6;
uint64 event_cursor = 7;
string project_id = 8;
```

### StudioProduction

```proto
string production_id = 1;
string request_id = 2;
StudioSource source = 3;
string external_order_id = 4;
string project_id = 5;
string task_profile_id = 6;
string recipe_id = 7;
uint64 recipe_revision = 8;
string flow_id = 9;
uint64 flow_revision = 10;
StudioRunStatus status = 11;
StudioStage stage = 12;
StudioCharacterRef character = 13;
string brief_id = 14;
uint64 brief_revision = 15;
string storyboard_id = 16;
uint64 storyboard_revision = 17;
string timeline_id = 18;
uint64 timeline_revision = 19;
repeated StudioNodeRun nodes = 20;
repeated StudioQualityCheck quality_checks = 21;
string active_export_id = 22;
StudioReviewVerdict overall_review = 23;
StudioApprovalPolicy review_policy = 24;
StudioProviderChoice provider_policy = 25;
StudioCost cost = 26;
uint32 priority = 27;
int64 deadline_unix_ms = 28;
uint64 revision = 29;
int64 created_unix_ms = 30;
int64 updated_unix_ms = 31;
int64 finished_unix_ms = 32;
uint64 progress_done = 33;
uint64 progress_total = 34;
StudioError error = 35;
bool ready_for_handoff = 36;
uint64 source_revision = 37;
bool test_order = 38;
repeated StudioAssetRef previews = 39;
uint64 last_event_cursor = 40;
string approval_record_id = 41;
bool can_pause = 42;
bool can_resume = 43;
bool can_cancel = 44;
bool can_rerun = 45;
string content_tier = 46;
```

### StudioExportManifest

```proto
string export_id = 1;
string production_id = 2;
uint64 production_revision = 3;
string project_id = 4;
StudioAssetRef final_asset = 5;
StudioOutputSpec output_spec = 6;
string storyboard_id = 7;
uint64 storyboard_revision = 8;
string timeline_id = 9;
uint64 timeline_revision = 10;
string flow_id = 11;
uint64 flow_revision = 12;
repeated StudioQualityCheck checks = 13;
StudioReviewVerdict verdict = 14;
bool operator_review_required = 15;
bool ready_for_handoff = 16;
bool revoked = 17;
string revoked_reason = 18;
uint64 revocation_revision = 19;
int64 created_unix_ms = 20;
string content_tier = 21;
repeated string input_asset_sha256 = 22;
repeated string model_sha256 = 23;
string render_adapter_revision = 24;
string exporter_version = 25;
uint64 revision = 26;
string approval_record_id = 27;
```

### StudioApprovalRecord

```proto
string approval_id = 1;
string production_id = 2;
string export_id = 3;
uint64 export_revision = 4;
uint64 production_revision = 5;
StudioReviewVerdict verdict = 6;
string reviewer_id = 7;
string reason = 8;
int64 decided_unix_ms = 9;
uint64 revision = 10;
repeated StudioQualityCheck evidence = 11;
bool superseded = 12;
```

### StudioHandoff

```proto
string handoff_id = 1;
string production_id = 2;
string customer_order_id = 3;
string export_id = 4;
string export_sha256 = 5;
uint64 byte_size = 6;
string mime = 7;
string content_tier = 8;
uint64 qc_revision = 9;
StudioReviewVerdict qc_verdict = 10;
bool review_required = 11;
uint64 studio_revision = 12;
uint64 order_revision = 13;
uint64 revocation_revision = 14;
string status = 15;
string revoked_reason = 16;
int64 created_unix_ms = 17;
int64 updated_unix_ms = 18;
string approval_id = 19;
uint64 revision = 20;
string source_request_id = 21;
bool dispatch_gate_checked = 22;
int64 last_gate_check_unix_ms = 23;
```

### StudioHandoffValidity

```proto
string handoff_id = 1;
string export_id = 2;
uint64 export_revision = 3;
uint64 studio_revision = 4;
bool current = 5;
bool revoked = 6;
bool asset_present = 7;
bool sha256_matches = 8;
StudioReviewVerdict current_qc = 9;
string content_tier = 10;
string reason_code = 11;
int64 checked_unix_ms = 12;
```

### StudioQueueItem

```proto
string queue_id = 1;
string production_id = 2;
string node_run_id = 3;
StudioResourceClass resource = 4;
StudioSource source = 5;
uint32 priority = 6;
StudioStepStatus status = 7;
int64 enqueued_unix_ms = 8;
int64 earliest_start_unix_ms = 9;
int64 deadline_unix_ms = 10;
uint64 estimated_memory_bytes = 11;
uint64 estimated_duration_ms = 12;
uint64 elapsed_ms = 13;
uint32 progress_current = 14;
uint32 progress_total = 15;
string block_reason = 16;
string model_id = 17;
bool admission_allowed = 18;
```

### StudioProductionSummary

```proto
string production_id = 1;
string project_id = 2;
string title = 3;
StudioSource source = 4;
StudioTaskKind task = 5;
StudioRunStatus status = 6;
StudioStage stage = 7;
StudioCharacterRef character = 8;
uint32 scene_count = 9;
uint64 duration_ms = 10;
StudioAssetRef preview = 11;
uint64 revision = 12;
int64 updated_unix_ms = 13;
string external_order_id = 14;
bool needs_review = 15;
bool can_open_in_studio = 16;
```

## studio_commands.proto

### StudioProjectUpsert

```proto
StudioProject project = 1;
uint64 expected_revision = 2;
```

### StudioProjectArchive

```proto
string project_id = 1;
uint64 expected_revision = 2;
bool archived = 3;
```

### StudioTaskSelect

```proto
string project_id = 1;
string task_profile_id = 2;
string recipe_id = 3;
uint64 recipe_revision = 4;
uint64 expected_project_revision = 5;
```

### StudioRecipeUpsert

```proto
StudioRecipeVersion recipe = 1;
uint64 expected_revision = 2;
```

### StudioRecipeActivate

```proto
string task_profile_id = 1;
string recipe_id = 2;
uint64 recipe_revision = 3;
uint64 expected_profile_version = 4;
string comparison_id = 5;
```

### StudioProductionSubmit

```proto
StudioProductionRequest production = 1;
```

### StudioProductionControl

```proto
string production_id = 1;
uint64 expected_revision = 2;
StudioProductionOperation operation = 3;
string reason = 4;
```

### StudioProductionRerun

```proto
string production_id = 1;
uint64 expected_revision = 2;
string from_node_id = 3;
string scene_id = 4;
string shot_id = 5;
bool include_transitive_descendants = 6;
string reason = 7;
```

### StudioAssetImport

```proto
string project_id = 1;
uint64 existing_media_id = 2;
uint64 existing_reference_id = 3;
bytes inline_bytes = 4;
string staged_upload_id = 5;
string filename = 6;
string mime = 7;
string declared_sha256 = 8;
StudioMediaKind kind = 9;
repeated StudioReferenceRole roles = 10;
string content_tier = 11;
bool allowed_for_external_provider = 12;
```

### StudioAssetRoleUpdate

```proto
string project_id = 1;
string reference_binding_id = 2;
repeated StudioReferenceRole roles = 3;
string scene_id = 4;
string shot_id = 5;
string actor_id = 6;
optional double strength = 7;
uint64 expected_revision = 8;
```

### StudioAssetDetach

```proto
string project_id = 1;
string reference_binding_id = 2;
uint64 expected_revision = 3;
```

### StudioBriefUpsert

```proto
StudioCreativeBrief brief = 1;
uint64 expected_revision = 2;
```

### StudioScriptGenerate

```proto
string brief_id = 1;
uint64 brief_revision = 2;
string project_id = 3;
StudioModelRef selected_model = 4;
string prompt_template_id = 5;
uint64 prompt_template_revision = 6;
uint32 desired_shots = 7;
string operator_note = 8;
StudioProviderChoice policy = 9;
```

### StudioScriptUpsert

```proto
StudioScriptVersion script = 1;
uint64 expected_revision = 2;
```

### StudioStoryboardGenerate

```proto
string script_id = 1;
uint64 script_revision = 2;
string project_id = 3;
StudioProviderChoice provider = 4;
uint64 target_duration_ms = 5;
StudioOutputSpec output = 6;
```

### StudioStoryboardUpsert

```proto
StudioStoryboard storyboard = 1;
uint64 expected_revision = 2;
```

### StudioSceneUpsert

```proto
string storyboard_id = 1;
uint64 expected_storyboard_revision = 2;
StudioScene scene = 3;
uint64 expected_scene_revision = 4;
```

### StudioShotUpsert

```proto
string storyboard_id = 1;
uint64 expected_storyboard_revision = 2;
string scene_id = 3;
StudioShot shot = 4;
uint64 expected_shot_revision = 5;
```

### StudioShotRemove

```proto
string storyboard_id = 1;
uint64 expected_storyboard_revision = 2;
string scene_id = 3;
string shot_id = 4;
uint64 expected_shot_revision = 5;
```

### StudioLookUpsert

```proto
StudioLookPreset look = 1;
uint64 expected_revision = 2;
```

### StudioCharacterSheetUpdate

```proto
uint64 character_id = 1;
uint64 expected_revision = 2;
repeated StudioReference identity_references = 3;
repeated StudioLookRef looks = 4;
StudioLookRef default_look = 5;
```

### StudioTrainingStart

```proto
uint64 character_id = 1;
string dataset_id = 2;
string registered_workflow_key = 3;
StudioModelRef base_model = 4;
uint32 steps = 5;
uint32 rank = 6;
string trigger = 7;
uint64 expected_character_revision = 8;
```

### StudioTrainingControl

```proto
string training_id = 1;
uint64 expected_revision = 2;
StudioProductionOperation operation = 3;
string checkpoint_asset_id = 4;
```

### StudioFlowUpsert

```proto
StudioFlowDefinition definition = 1;
uint64 expected_revision = 2;
```

### StudioFlowValidate

```proto
StudioFlowDefinition draft = 1;
bool check_live_capabilities = 2;
```

### StudioFlowActivate

```proto
string flow_id = 1;
uint64 flow_revision = 2;
uint64 expected_recipe_revision = 3;
string recipe_id = 4;
```

### StudioFlowNodeUpdate

```proto
string flow_id = 1;
uint64 expected_flow_revision = 2;
StudioNodeDefinition node = 3;
uint64 expected_node_revision = 4;
```

### StudioFlowNodeRemove

```proto
string flow_id = 1;
uint64 expected_flow_revision = 2;
string node_id = 3;
bool remove_connected_edges = 4;
```

### StudioModelRegistryRefresh

```proto
string provider_account_id = 1;
bool local_models = 2;
```

### StudioModelRegister

```proto
StudioModelCapability model = 1;
uint64 expected_catalog_version = 2;
string validated_import_asset_id = 3;
```

### StudioModelSetQualification

```proto
string model_id = 1;
string capability_id = 2;
StudioEvidence evidence = 3;
repeated string test_evidence_ids = 4;
uint64 expected_catalog_version = 5;
```

### StudioProviderAccountUpsert

```proto
StudioProviderAccount account = 1;
uint64 expected_revision = 2;
```

### StudioProviderSecretReplace

```proto
string account_id = 1;
string secret_utf8 = 2;
uint64 expected_account_revision = 3;
```

### StudioProviderSecretClear

```proto
string account_id = 1;
uint64 expected_account_revision = 2;
```

### StudioProviderAccountRemove

```proto
string account_id = 1;
uint64 expected_revision = 2;
```

### StudioProviderTest

```proto
string account_id = 1;
string model_id = 2;
bool test_auth = 3;
bool test_model_listing = 4;
bool test_schema_response = 5;
StudioMoney maximum_test_cost = 6;
```

### StudioProviderModelsRefresh

```proto
string account_id = 1;
```

### StudioRoleBindingUpsert

```proto
StudioRoleBinding binding = 1;
uint64 expected_revision = 2;
```

### StudioGlobalProviderSettingsUpdate

```proto
StudioProviderPolicy default_policy = 1;
bool external_providers_master_enabled = 2;
bool customer_conversation_external_enabled = 3;
StudioMoney global_monthly_budget = 4;
uint64 expected_version = 5;
```

### StudioDirectorRequest

```proto
string project_id = 1;
string brief_id = 2;
uint64 brief_revision = 3;
string storyboard_id = 4;
uint64 storyboard_revision = 5;
string scene_id = 6;
string shot_id = 7;
string operator_message = 8;
StudioModelRole role = 9;
StudioProviderChoice provider = 10;
string conversation_session_id = 11;
bool only_suggest = 12;
```

### StudioDirectorNoteDecision

```proto
string script_id = 1;
uint64 script_revision = 2;
string note_id = 3;
bool accept = 4;
string operator_reason = 5;
```

### StudioSceneSpecUpsert

```proto
StudioSceneSpec scene_spec = 1;
uint64 expected_revision = 2;
```

### StudioBlenderBuild

```proto
string scene_spec_id = 1;
uint64 scene_spec_revision = 2;
string render_preset_id = 3;
bool preview_only = 4;
repeated StudioGuideTransfer passes = 5;
StudioMoney cost_ceiling = 6;
```

### StudioGuideApproval

```proto
string guide_id = 1;
uint64 guide_revision = 2;
bool approved = 3;
string reason = 4;
```

### StudioGuideCompareRequest

```proto
string guide_id = 1;
string output_asset_id = 2;
repeated string metric_ids = 3;
```

### StudioCameraInputRegister

```proto
string scene_spec_id = 1;
uint64 expected_revision = 2;
string camera_id = 3;
StudioCameraExternalInput camera_input = 4;
```

### StudioCameraInputCalibration

```proto
string input_id = 1;
string calibration_id = 2;
StudioQuat neutral_rotation = 3;
StudioVec3 neutral_translation_m = 4;
string axes_id = 5;
int64 time_offset_ms = 6;
```

### StudioBlockingSettingsUpdate

```proto
string scene_spec_id = 1;
uint64 expected_revision = 2;
string camera_id = 3;
StudioBlockingMode blocking_mode = 4;
repeated StudioGuideTransfer transfer = 5;
StudioCameraControl camera_control = 6;
bool transfer_actor_pose = 7;
bool transfer_actor_position = 8;
bool transfer_source_appearance = 9;
string target_actor_id = 10;
```

### StudioTimelineUpsert

```proto
StudioTimeline timeline = 1;
uint64 expected_revision = 2;
```

### StudioExportRequest

```proto
string production_id = 1;
uint64 expected_revision = 2;
string timeline_id = 3;
uint64 timeline_revision = 4;
StudioOutputSpec output = 5;
string export_profile_id = 6;
bool perform_qualification_checks = 7;
```

### StudioExportReview

```proto
string export_id = 1;
uint64 export_revision = 2;
StudioReviewVerdict verdict = 3;
string reason = 4;
```

### StudioExportRevoke

```proto
string export_id = 1;
uint64 expected_revision = 2;
string reason = 3;
```

### StudioComparisonStart

```proto
string project_id = 1;
string task_profile_id = 2;
repeated string candidate_model_ids = 3;
repeated string workflow_keys = 4;
repeated StudioReference reference_set = 5;
string prompt = 6;
StudioMoney cost_ceiling = 7;
```

### StudioComparisonSelect

```proto
string comparison_id = 1;
uint64 expected_revision = 2;
string selected_candidate_id = 3;
bool activate_as_standard = 4;
```

### StudioQueueControl

```proto
string queue_id = 1;
StudioProductionOperation operation = 2;
string reason = 3;
uint64 expected_resource_version = 4;
```

### StudioPromptTemplateUpsert

```proto
StudioPromptTemplate template = 1;
uint64 expected_revision = 2;
```

### StudioShotPresetUpsert

```proto
StudioShotPreset preset = 1;
uint64 expected_revision = 2;
```

### StudioAudioGenerate

```proto
string production_id = 1;
string shot_id = 2;
StudioAudioCue cue = 3;
StudioProviderChoice provider = 4;
StudioMoney cost_ceiling = 5;
```

### StudioAudioPresetUpsert

```proto
StudioAudioProviderPreset preset = 1;
uint64 expected_revision = 2;
```

## studio_stream.proto

### StudioTasksState

```proto
repeated StudioTaskProfile tasks = 1;
repeated StudioRecipeVersion active_recipes = 2;
uint64 version = 3;
StudioModelCatalog models_summary = 4;
repeated StudioOutputProfile output_profiles = 5;
```

### StudioProductionsState

```proto
repeated StudioProductionSummary recent = 1;
repeated StudioProductionSummary running = 2;
repeated StudioProductionSummary waiting_review = 3;
uint64 version = 4;
uint64 last_event_cursor = 5;
```

### StudioProjectsState

```proto
repeated StudioProject recent = 1;
uint64 version = 2;
```

### StudioStoryboardsState

```proto
repeated StudioStoryboard recent = 1;
uint64 version = 2;
uint64 last_event_cursor = 3;
```

### StudioQueueState

```proto
repeated StudioQueueItem running = 1;
repeated StudioQueueItem pending = 2;
repeated StudioQueueItem paused = 3;
uint64 version = 4;
uint32 total_pending = 5;
```

### StudioProvidersState

```proto
StudioProviderSettings settings = 1;
uint64 version = 2;
```

### StudioFlowsState

```proto
repeated StudioFlowSummary flows = 1;
uint64 version = 2;
```

### StudioFlowSummary

```proto
string flow_id = 1;
uint64 revision = 2;
string title = 3;
string recipe_id = 4;
StudioEvidence qualification = 5;
bool active = 6;
bool customer_enabled = 7;
uint32 node_count = 8;
uint32 edge_count = 9;
bool editable = 10;
```

### StudioResourcesState

```proto
StudioResourceState resources = 1;
uint64 version = 2;
```

### StudioCharactersState

```proto
repeated StudioCharacterSheet character_sheets = 1;
repeated StudioTrainingRun recent_training = 2;
uint64 version = 3;
```

### StudioProductionChanged

```proto
string production_id = 1;
uint64 revision = 2;
StudioRunStatus status = 3;
StudioStage stage = 4;
string event_kind = 5;
StudioError error = 6;
uint64 last_event_cursor = 7;
string request_id = 8;
string export_id = 9;
```

### StudioNodeRunChanged

```proto
string production_id = 1;
string node_run_id = 2;
string node_id = 3;
string scene_id = 4;
string shot_id = 5;
StudioStepStatus status = 6;
uint64 revision = 7;
uint64 progress_current = 8;
uint64 progress_total = 9;
StudioError error = 10;
repeated string result_asset_ids = 11;
string request_id = 12;
bool cache_hit = 13;
```

### StudioAssetChanged

```proto
StudioAssetRef asset = 1;
string change = 2;
string project_id = 3;
string production_id = 4;
string node_run_id = 5;
```

### StudioProjectChanged

```proto
string project_id = 1;
uint64 revision = 2;
string change = 3;
string request_id = 4;
```

### StudioCreativeChanged

```proto
string project_id = 1;
string brief_id = 2;
uint64 brief_revision = 3;
string script_id = 4;
uint64 script_revision = 5;
string storyboard_id = 6;
uint64 storyboard_revision = 7;
string scene_id = 8;
string shot_id = 9;
string change = 10;
string request_id = 11;
repeated string invalidated_node_ids = 12;
```

### StudioFlowChanged

```proto
string flow_id = 1;
uint64 revision = 2;
string change = 3;
string recipe_id = 4;
string request_id = 5;
StudioFlowValidation validation = 6;
```

### StudioProviderChanged

```proto
string account_id = 1;
uint64 revision = 2;
string change = 3;
string status = 4;
StudioError error = 5;
string request_id = 6;
```

### StudioCharacterChanged

```proto
uint64 character_id = 1;
uint64 revision = 2;
string change = 3;
string training_id = 4;
string lora_key = 5;
string request_id = 6;
```

### StudioGuideChanged

```proto
string guide_id = 1;
uint64 revision = 2;
string scene_spec_id = 3;
string shot_id = 4;
string change = 5;
StudioReviewVerdict verdict = 6;
StudioError error = 7;
```

### StudioExportChanged

```proto
string export_id = 1;
string production_id = 2;
uint64 export_revision = 3;
string change = 4;
StudioReviewVerdict verdict = 5;
bool revoked = 6;
string revoked_reason = 7;
string asset_sha256 = 8;
```

### StudioHandoffChanged

```proto
string handoff_id = 1;
string production_id = 2;
string customer_order_id = 3;
string export_id = 4;
uint64 revocation_revision = 5;
string status = 6;
string reason = 7;
uint64 revision = 8;
```

### StudioDirectorResult

```proto
string request_id = 1;
string project_id = 2;
string production_id = 3;
string brief_id = 4;
string script_id = 5;
string storyboard_id = 6;
string proposed_note_id = 7;
string suggestion_text = 8;
StudioModelRef model = 9;
StudioCost cost = 10;
StudioError error = 11;
bool accepted_into_plan = 12;
```

### StudioFlowValidated

```proto
string request_id = 1;
StudioFlowValidation validation = 2;
StudioError error = 3;
```

### StudioComparisonChanged

```proto
string comparison_id = 1;
string project_id = 2;
string change = 3;
uint64 revision = 4;
string selected_candidate_id = 5;
StudioError error = 6;
```

### StudioReadById

```proto
string id = 1;
uint64 revision = 2;
```

### StudioListFilter

```proto
string page_token = 1;
uint32 limit = 2;
string project_id = 3;
string production_id = 4;
StudioSource source = 5;
StudioTaskKind task = 6;
StudioRunStatus status = 7;
string search = 8;
bool include_archived = 9;
string kind = 10;
```

### StudioReadRequest

```proto
StudioListFilter list_projects = 1;
StudioListFilter list_productions = 2;
StudioListFilter list_assets = 3;
StudioListFilter list_flows = 4;
StudioListFilter list_training = 5;
StudioReadById get_project = 6;
StudioReadById get_production = 7;
StudioReadById get_flow = 8;
StudioReadById get_storyboard = 9;
StudioReadById get_script = 10;
StudioReadById get_brief = 11;
StudioReadById get_scene_spec = 12;
StudioReadById get_guide = 13;
StudioReadById get_timeline = 14;
StudioReadById get_export = 15;
StudioReadById get_handoff_validity = 16;
StudioReadById get_comparison = 17;
StudioReadById get_training = 18;
StudioReadById get_asset = 19;
StudioReadById get_character_sheet = 20;
StudioListFilter list_looks = 21;
StudioReadById get_look = 22;
StudioReadById get_node_run = 23;
StudioListFilter list_provider_usage = 24;
```

### StudioProjectsPage

```proto
repeated StudioProject items = 1;
StudioPageInfo page = 2;
```

### StudioProductionsPage

```proto
repeated StudioProductionSummary items = 1;
StudioPageInfo page = 2;
```

### StudioAssetsPage

```proto
repeated StudioAssetRef items = 1;
StudioPageInfo page = 2;
```

### StudioFlowsPage

```proto
repeated StudioFlowSummary items = 1;
StudioPageInfo page = 2;
```

### StudioTrainingPage

```proto
repeated StudioTrainingRun items = 1;
StudioPageInfo page = 2;
```

### StudioLooksPage

```proto
repeated StudioLookPreset items = 1;
StudioPageInfo page = 2;
```

### StudioProviderUsagePage

```proto
repeated StudioProviderUsage items = 1;
StudioPageInfo page = 2;
```

### StudioReadResponse

```proto
StudioError error = 1;
StudioProjectsPage projects = 2;
StudioProductionsPage productions = 3;
StudioAssetsPage assets = 4;
StudioFlowsPage flows = 5;
StudioTrainingPage trainings = 6;
StudioProject project = 7;
StudioProduction production = 8;
StudioFlowDefinition flow = 9;
StudioStoryboard storyboard = 10;
StudioScriptVersion script = 11;
StudioCreativeBrief brief = 12;
StudioSceneSpec scene_spec = 13;
StudioGuideBundle guide = 14;
StudioTimeline timeline = 15;
StudioExportManifest export_manifest = 16;
StudioHandoffValidity handoff_validity = 17;
StudioComparisonRun comparison = 18;
StudioTrainingRun training = 19;
StudioAssetRef asset = 20;
StudioCharacterSheet character_sheet = 21;
StudioLooksPage looks = 22;
StudioLookPreset look = 23;
StudioNodeRun node_run = 24;
StudioProviderUsagePage provider_usage = 25;
```
