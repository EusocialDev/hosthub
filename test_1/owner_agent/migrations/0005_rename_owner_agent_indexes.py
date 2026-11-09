from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("owner_agent", "0004_owneragentassessment_flow_reasons"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="owneragentanalysis",
            old_name="owner_agent__status_3d6609_idx",
            new_name="owner_agent_status_77bf57_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentanalysis",
            old_name="owner_agent__reservat_8e7295_idx",
            new_name="owner_agent_reserva_408a80_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentassessment",
            old_name="owner_agent__status_0b5ff3_idx",
            new_name="owner_agent_status_7f5bba_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentassessment",
            old_name="owner_agent__reason_9d4181_idx",
            new_name="owner_agent_reason_13fb81_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentdigest",
            old_name="owner_agent__account_3e4a18_idx",
            new_name="owner_agent_account_6d70cd_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentdigest",
            old_name="owner_agent__status_9dd99d_idx",
            new_name="owner_agent_status_5418e9_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentdigestitem",
            old_name="owner_agent__digest_i_57bbdd_idx",
            new_name="owner_agent_digest__8fe327_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentmessage",
            old_name="owner_agent__account_3fe8b5_idx",
            new_name="owner_agent_account_512d09_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentmessage",
            old_name="owner_agent__owner_p_6d6e3b_idx",
            new_name="owner_agent_owner_p_6df97c_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentmessage",
            old_name="owner_agent__ghl_con_5d9c4e_idx",
            new_name="owner_agent_ghl_con_ca216c_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentsettings",
            old_name="owner_agent__enabled_8eb0ab_idx",
            new_name="owner_agent_enabled_a2b478_idx",
        ),
        migrations.RenameIndex(
            model_name="owneragentsettings",
            old_name="owner_agent__owner_p_3c01fd_idx",
            new_name="owner_agent_owner_p_1c33de_idx",
        ),
    ]
