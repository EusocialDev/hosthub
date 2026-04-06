from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.conf import settings

# Disposition (how the call was handled) choices
DISPOSITION_CHOICES = [
    ("reservation_placed", "Reservation Placed by Host"),
    ("reservation_link", "Reservation Placed via Link Sent to Caller"),
    ("reservation_update", "Reservation Successfully Updated by Host"),
    ("reservation_canceled", "Reservation Canceled by Host"),

    ("carryout_ai_host", "Carryout Order Placed via AI Host"),
    ("carryout_link", "Carryout Order Placed via Link Sent to Caller"),

    ("message_handled", "Message Left by Caller Handled by Host"),

    ("questions_answered", "Caller Had Questions That Were Answered by AI Host"),

    ("private_party", "Informed Manager About Private Party First Inquiry"),
    ("private_party_message", "Informed Manager About Message Left About Existing Private Party"),

    ("other", "Other"),
]

class Call(models.Model):
    # Tenant Info
    account = models.ForeignKey(
        "Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calls",
    )
    location = models.ForeignKey(
        "Location",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calls",
    )
    phone_number = models.ForeignKey(
        "PhoneNumber",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calls",
    )

    # ID
    bland_call_id = models.CharField(max_length=250, unique=True)

    # Phone Info
    from_number = models.CharField(max_length=50, null=True, blank=True)
    to_number = models.CharField(max_length=50, null=True, blank=True)

    # User name
    user_name = models.CharField(max_length=50, null=True, blank=True)

    # Time Stamps
    created_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null= True, blank=True)

    # Duration 
    duration_seconds = models.IntegerField(null=True, blank=True)

    # Status
    queue_status = models.CharField(max_length=50, null=True, blank=True)
    bland_status = models.CharField(max_length=50, null=True, blank=True)
    completed = models.BooleanField(default=False)

    # Content
    summary = models.TextField(null=True, blank=True)
    full_transcript = models.TextField(null=True, blank=True)
    transcripts = models.JSONField(null=True, blank=True)

    pathway_tags = ArrayField(
        base_field=models.CharField(max_length=255),
        default=list,
        blank= True,
        null=True
    )

    variables = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)

    # HostHub Categories
    display_category = models.CharField(
        max_length=50,
        default="other",
        choices=[
            ("reservation", "Reservation"),
            ("carryout", "Carryout"),
            ("leave_message", "Leave a message"),
            ("other", "Other"),
            ("private_events", "Private Events"),
        ]
    )

    #Ingestion status
    ingested_at = models.DateTimeField(null=True, blank=True)

    # HostHub Host actions 
    host_status = models.CharField(
        max_length=50,
        default="needs_action",
        choices=[
            ("needs_action", "Needs Action"),
            ("resolved", "Resloved"),
        ]
    )


    notes = models.TextField(null=True, blank=True)    
    
    # Handled info
    handled_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.CharField(max_length=20, choices=[
        ("david", "David"),
        ("derek", "Derek"),
        ('gabriel', "Gabriel"),
        ('brian','Brian'),
        ('miguel', 'Miguel'),
        ('adiana', 'Adriana')
    ], null=True, blank=True)
    disposition = models.CharField(max_length=50, choices=DISPOSITION_CHOICES, null=True, blank=True)


    def mark_resolved(self, handled_by=None, disposition=None):
        self.host_status = "resolved"
        self.handled_at = timezone.now()
        if handled_by:
            self.handled_by = handled_by
        if disposition:
            self.disposition = disposition
        
        self.save()

    def __str__(self):
        return f"Call from {self.user_name} phone number: {self.from_number} about: ({self.display_category})"

class CallSession(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        TRANSFERRED = "transferred", "Transferred"
        ABANDONED = "abandoned", "Abandoned"

    call_id = models.CharField(max_length=250, unique=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )

    from_number=models.CharField(
        max_length=30,
        null=True,
        blank=True,
        db_index=True,
        help_text="Caller phone number (from Bland 'from' field)"

    )

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    last_event_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "updated_at"]),
        ]

class TranscriptTurn(models.Model):
    class Role(models.TextChoices):
        AGENT = "agent", "Agent"
        USER = "user", "User"
    
    call = models.ForeignKey(
        CallSession,
        on_delete=models.CASCADE,
        related_name="transcript_turns",
        db_index=True,
    )
    
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        db_index=True,
    )

    text = models.TextField(blank=True, null=True)

    sequence = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    dedupe_hash = models.CharField(max_length=64, blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["sequence"]
        indexes = [
            models.Index(fields=["call", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["call", "sequence"], name="unique_seq_per_call", condition=models.Q(sequence__isnull=False))
        ]

class CallAlert(models.Model):
    class Severity(models.TextChoices):
        YELLOW = "yellow", "Yellow"
        RED = "red", "Red"

    call = models.ForeignKey(
        CallSession,
        on_delete=models.CASCADE,
        related_name='alerts',
        db_index=True,
    )
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        db_index=True,
    )
    reason_code = models.CharField(max_length=80, blank=True, null=True)
    message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["resolved_at", "severity", "-created_at"]),
            models.Index(fields=["call", "resolved_at"]),
        ]



# ------------------------
# MULTI-TENANT MODELS
# ------------------------

class Account(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)

    #For future integration with Eusocial
    external_platform_id = models.CharField(max_length=255, blank=True, null=True)

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Location(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='locations')
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    slug = models.SlugField(max_length=255, unique=True, null=True, blank=True)

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.account.name} - {self.name}"

class UserAccess(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("manager", "Manager"),
        ("host", "Host"),
    ]
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hosthub_access",
    )

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="user_accesses",
    )

    locations = models.ManyToManyField(
        Location,
        related_name="authorized_users",
        blank=True,
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="host")

    pin_hash = models.CharField(max_length=128, blank=True, null=True)

    def set_pin(self, raw_pin):
        self.pin_hash = make_password(raw_pin)
    
    def check_pin(self, raw_pin):
        if not self.pin_hash:
            return False
        return check_password(raw_pin, self.pin_hash)

    is_active = models.BooleanField(default=True)

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if not self.pk:
            return

        for location in self.locations.all():
            if location.account_id != self.account_id:
                raise ValidationError("All assigned locations must belong to the same account.")

    def __str__(self):
        return f"{self.user.username} -> {self.account.name} ({self.role})"

class PhoneNumber(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='phone_numbers')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='phone_numbers')
    number = models.CharField(max_length=20, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.location and self.account and self.location.account_id != self.account_id:
            raise ValidationError("Location must belong to the same account as the phone number.")
            
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} -> {self.location.name} ({self.account.name})"


