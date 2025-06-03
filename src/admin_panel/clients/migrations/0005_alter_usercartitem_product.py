import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0004_alter_usercartitem_product'),
    ]

    operations = [
        migrations.AlterField(
            model_name='usercartitem',
            name='product',
            field=models.ForeignKey(help_text='Товар, добавленный в корзину.', on_delete=django.db.models.deletion.CASCADE, to='clients.product', verbose_name='Товар'),
        ),
    ]
