from django import forms
from django.contrib.auth import get_user_model
from .models import Match, MatchAssignment, Season, Competition, CompetitionPhase, Team, Venue

User = get_user_model()


class MatchForm(forms.ModelForm):
    """Form for creating/editing matches."""

    class Meta:
        model = Match
        fields = ['date', 'time', 'venue', 'court', 'home_team', 'away_team', 'phase', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'),
            'time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}, format='%H:%M'),
            'venue': forms.Select(attrs={'class': 'form-control'}),
            'court': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'pl. 1-es pálya'}),
            'home_team': forms.Select(attrs={'class': 'form-control'}),
            'away_team': forms.Select(attrs={'class': 'form-control'}),
            'phase': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sort teams - TBD first, then alphabetically
        self.fields['home_team'].queryset = Team.objects.filter(is_active=True).order_by('-is_tbd', 'name')
        self.fields['away_team'].queryset = Team.objects.filter(is_active=True).order_by('-is_tbd', 'name')
        # Filter phase by current season
        current_season = Season.get_current()
        if current_season:
            self.fields['phase'].queryset = CompetitionPhase.objects.filter(
                competition__season=current_season
            ).select_related('competition')


class MatchAssignmentForm(forms.Form):
    """Form for assigning referees to a match."""

    referee1 = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label='1. Játékvezető',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    referee2 = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label='2. Játékvezető',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    inspector = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label='Ellenőr',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    reserve = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label='Tartalék',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, match=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.match = match

        # Base queryset: active users who can be assigned to matches
        # Excludes: deleted, login disabled, hidden from colleagues
        assignable_users = User.objects.filter(
            role__in=['referee', 'jt_admin', 'admin', 'inspector'],
            is_deleted=False,
            is_login_disabled=False,
        ).order_by('last_name', 'first_name')

        # Update querysets for all fields
        for field_name in ['referee1', 'referee2', 'inspector', 'reserve']:
            self.fields[field_name].queryset = assignable_users
            self.fields[field_name].label_from_instance = lambda obj: obj.get_full_name() or obj.username

        # Pre-fill from existing assignments if editing
        if match:
            referees = list(match.get_referees().select_related('user'))
            if len(referees) > 0:
                self.fields['referee1'].initial = referees[0].user
            if len(referees) > 1:
                self.fields['referee2'].initial = referees[1].user

            inspectors = list(match.get_inspectors().select_related('user'))
            if inspectors:
                self.fields['inspector'].initial = inspectors[0].user

            reserves = list(match.get_reserves().select_related('user'))
            if reserves:
                self.fields['reserve'].initial = reserves[0].user

    def save(self):
        """Save assignments to the match."""
        if not self.match:
            return

        # Clear existing assignments
        self.match.assignments.all().delete()

        # Add referee 1
        if self.cleaned_data.get('referee1'):
            MatchAssignment.objects.create(
                match=self.match,
                user=self.cleaned_data['referee1'],
                role=MatchAssignment.Role.REFEREE
            )

        # Add referee 2
        if self.cleaned_data.get('referee2'):
            MatchAssignment.objects.create(
                match=self.match,
                user=self.cleaned_data['referee2'],
                role=MatchAssignment.Role.REFEREE
            )

        # Add inspector
        if self.cleaned_data.get('inspector'):
            MatchAssignment.objects.create(
                match=self.match,
                user=self.cleaned_data['inspector'],
                role=MatchAssignment.Role.INSPECTOR
            )

        # Add reserve
        if self.cleaned_data.get('reserve'):
            MatchAssignment.objects.create(
                match=self.match,
                user=self.cleaned_data['reserve'],
                role=MatchAssignment.Role.RESERVE
            )


class MatchResponseForm(forms.Form):
    """Form for accepting/declining a match assignment."""

    RESPONSE_CHOICES = [
        ('accepted', 'Elfogadom'),
        ('declined', 'Elutasítom'),
    ]

    response = forms.ChoiceField(
        choices=RESPONSE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'})
    )
    decline_reason = forms.CharField(
        required=False,
        max_length=300,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Elutasítás indoka...'
        })
    )

    def __init__(self, *args, require_reason=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_reason = require_reason

    def clean(self):
        cleaned_data = super().clean()
        response = cleaned_data.get('response')
        decline_reason = cleaned_data.get('decline_reason')

        # Only require decline reason if setting is enabled
        if self.require_reason and response == 'declined' and not decline_reason:
            self.add_error('decline_reason', 'Kérlek add meg az elutasítás okát.')

        return cleaned_data


class MatchFilterForm(forms.Form):
    """Form for filtering matches."""

    season = forms.ModelChoiceField(
        queryset=Season.objects.all(),
        required=False,
        label='Szezon',
        empty_label='Összes szezon',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    competition = forms.ModelChoiceField(
        queryset=Competition.objects.none(),
        required=False,
        label='Bajnokság',
        empty_label='Összes bajnokság',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_from = forms.DateField(
        required=False,
        label='Dátumtól',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    date_to = forms.DateField(
        required=False,
        label='Dátumig',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    team = forms.ModelChoiceField(
        queryset=Team.objects.all().order_by('-is_tbd', 'name'),
        required=False,
        label='Csapat',
        empty_label='Összes csapat',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_season = Season.get_current()
        if current_season:
            self.fields['season'].initial = current_season
            self.fields['competition'].queryset = Competition.objects.filter(season=current_season)

        # Set default date range to today + 7 days (only if no data provided)
        from django.utils import timezone
        from datetime import timedelta
        if not args or not args[0]:  # No GET data provided
            today = timezone.now().date()
            self.fields['date_from'].initial = today
            self.fields['date_to'].initial = today + timedelta(days=7)
